from pydantic import BaseModel, HttpUrl



# request models
class VideoSourceInfo(BaseModel):
    source: str = "FILE_UPLOAD"
    video_size: int
    chunk_size: int
    total_chunk_count: int = 1

class UploadInitRequest(BaseModel):
    source_info: VideoSourceInfo
    

class SourceInfo(BaseModel):
    source: str = "PULL_FROM_URL"
    video_url: HttpUrl

class TikTokPullUploadRequest(BaseModel):
    source_info: SourceInfo

