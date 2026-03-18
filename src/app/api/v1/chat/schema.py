from pydantic import BaseModel, Field


class ChatRequest(BaseModel):

    message: str = Field(..., min_length=1)
    #thread_id: str = Field(..., min_length=1) todo - make that optional, if null then in create new thread


