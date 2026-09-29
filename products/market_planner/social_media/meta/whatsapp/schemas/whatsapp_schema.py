from pydantic import BaseModel, Field


class WhatsAppNumberBody(BaseModel):
    phone_number: str


class PostSendRequest(BaseModel):
    company_id: str
    caption: str
    media_url: str


class ThemeSendRequest(BaseModel):
    """Body for POST .../whatsapp/themes/send/{theme_id}.

    By default, month + both options are read from the Theme row's ``data`` JSON
    (``month``, ``month_id``, ``themes[].title`` / ``description``).

    Pass any of the optional fields to override what was stored in the DB.
    """

    company_id: str
    month: str | None = Field(default=None, description="Override; otherwise from theme.data.month / month_id")
    option1_title: str | None = Field(default=None, description="Override; otherwise themes[0].title")
    option1_desc: str | None = Field(default=None, description="Override; otherwise themes[0].description")
    option2_title: str | None = Field(default=None, description="Override; otherwise themes[1].title")
    option2_desc: str | None = Field(default=None, description="Override; otherwise themes[1].description")
