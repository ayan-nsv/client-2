import os
import time
from byteplussdkarkruntime import Ark
from products.market_planner.integrations.openai.gpt_service import GPTservice
import asyncio
from dotenv import load_dotenv

load_dotenv()

def get_seedance_client():
    return Ark(
    base_url="https://ark.ap-southeast.bytepluses.com/api/v3", 
    api_key=os.getenv("ARK_API_KEY"), 
)

client = get_seedance_client()


def generate_prompt(
    query: str,
    ratio: str,
    resolution: str,
    duration: int,
) -> str:

    seedance_prompt = GPTservice().generate_prompt_for_seedance(query)

    technical_parameters = (
        f" --ratio {ratio}"
        f" --resolution {resolution}"
        f" --duration {duration}"
        f" --camerafixed false"
    )

    return seedance_prompt + technical_parameters


def generate_video(
    query: str,
    ratio: str,
    resolution: str,
    duration: int,
):

    prompt = generate_prompt(
        query=query,
        ratio=ratio,
        resolution=resolution,
        duration=duration,
    )

    print("----- Seedance prompt -----")
    print(prompt)

    create_result = client.content_generation.tasks.create(
        model="dreamina-seedance-2-0-mini-260615",
        content=[
            {
                "type": "text",
                "text": prompt,
            }
        ],
    )


    task_id = create_result.id

    max_wait = 600
    interval = 10
    start = time.time()

    while time.time() - start < max_wait:

        get_result = client.content_generation.tasks.get(
            task_id=task_id
        )

        status = get_result.status

        if status == "succeeded":


            video_url = get_result.content.video_url

            return {
                "task_id": task_id,
                "status": "succeeded",
                "video_url": video_url,
            }

        elif status == "failed":

            return {
                "task_id": task_id,
                "status": "failed",
                "error": get_result.error,
            }

        else:


            time.sleep(interval)

            interval = min(interval * 1.5, 30)

    raise TimeoutError(
        f"Task {task_id} timed out after {max_wait}s."
    )


