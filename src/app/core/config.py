from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Manfred API"
    VERSION: str = "0.0.0-dev"
    DESCRIPTION: str = "Empty description"
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 3333
    

