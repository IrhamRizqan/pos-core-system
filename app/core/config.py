from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME:str = "POS Core Engine"
    DATABASE_URL:str = "mysql+asyncmy://root:rootpassword@localhost:3306/pos_db"
    REDIS_URL:str = "redis://localhost:6380/0"
    JWT_SECRET_KEY:str = "BdC4Sn707BcHL0dBPTAlZdbjCYOvnltFG4wsSOcgD2R"
    JWT_ALGORITHM:str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES:int = 480 #per shift 8 jam

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()