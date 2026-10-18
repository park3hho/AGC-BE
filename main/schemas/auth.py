from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    username: str = Field(max_length=50)
    password: str = Field(max_length=200)
    remember: bool = False

    @field_validator("username")
    @classmethod
    def normalize_username(cls, v):
        return v.strip().lower()
