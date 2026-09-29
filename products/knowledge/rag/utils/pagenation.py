from math import ceil
from typing import Any, List, Tuple
from sqlalchemy.orm import Query
from fastapi import Request


def paginate_query(
    query: Query,
    request: Request,
    page: int,
    page_size: int
) -> Tuple[List[Any], dict]:

    total_items = query.count()

    if total_items == 0:
        return [], {
            "number_of_pages": 0,
            "current_page": page,
            "next": None,
            "previous": None,
        }

    number_of_pages = ceil(total_items / page_size)

    if page > number_of_pages:
        raise ValueError("Page number exceeds total pages")

    items = (
        query
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    base_url = str(request.url).split("?")[0]

    def build_url(target_page: int):
        return f"{base_url}?page={target_page}&page_size={page_size}"

    pagination = {
        "number_of_pages": number_of_pages,
        "current_page": page,
        "next": build_url(page + 1) if page < number_of_pages else None,
        "previous": build_url(page - 1) if page > 1 else None,
    }

    return items, pagination
