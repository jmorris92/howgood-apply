from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ApplicationPayload(BaseModel):
    """The documented request body. Unknown keys in the config file are ignored."""

    name: NonBlank
    email: NonBlank
    resume: NonBlank
    location: NonBlank
    linkedin: NonBlank
    codeLink: NonBlank
    yearsPython: int | None = None
    yearsDjango: int | None = None
    repos: str | None = None
    notes: str | None = None

    model_config = ConfigDict(
            strict=True,
            extra="ignore",
            json_schema_extra={
                "examples": [
                    {
                        "name": "Milton Waddams",
                        "email": "milton.waddams@initech.example",
                        "resume": "https://drive.example.com/milton-waddams-resume.pdf",
                        "location": "Austin, TX, USA",
                        "linkedin": "https://www.linkedin.com/in/milton-waddams-example",
                        "codeLink": "https://github.com/milton-waddams/howgood-application",
                        "yearsPython": 6,
                        "yearsDjango": 2,
                        "repos": "https://github.com/milton-waddams",
                        "notes": "I believe you have my stapler.",
                    }
                ]
            },
        )
