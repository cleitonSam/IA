from pydantic import BaseModel
from typing import Optional, Dict, Any, List


class ContactModel(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None


class ConversationModel(BaseModel):
    id: Optional[int] = None
    status: Optional[str] = None
    assignee_id: Optional[int] = None


class AccountModel(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None


class MessageAttachment(BaseModel):
    file_type: Optional[str] = None
    data_url: Optional[str] = None


class MessageModel(BaseModel):
    id: Optional[int] = None
    content: Optional[str] = None
    message_type: Optional[str] = None
    content_type: Optional[str] = None
    attachments: Optional[list] = None


class ChatwootWebhookPayload(BaseModel):
    event: Optional[str] = None
    id: Optional[int] = None
    account: Optional[AccountModel] = None
    conversation: Optional[ConversationModel] = None
    message_type: Optional[str] = None
    content: Optional[str] = None
    contact: Optional[ContactModel] = None

    class Config:
        extra = "allow"
