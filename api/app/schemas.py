"""Schemas de fronteira (Pydantic v2). O frontend gera seus tipos a partir do OpenAPI destes modelos."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Hex = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class UserConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tier: Literal["quick", "default", "complex"] = "default"
    readMode: Literal["agent", "direct"] = "agent"
    length: Literal["curta", "media", "detalhada"] = "media"
    showSteps: bool = True
    showSources: bool = True
    groupMode: Literal["auto", "todos"] = "auto"
    groupMax: Literal[1, 2, 3] = 2
    receipts: bool = True
    typing: bool = True
    theme: Literal["system", "light", "dark"] = "system"
    fontSize: Literal[14, 15, 17] = 15
    enterSend: bool = True


class Me(BaseModel):
    id: UUID
    name: str
    email: str | None
    settings: UserConfig
    usage_today: int
    daily_limit: int
    is_admin: bool = False
    is_master: bool = False
    tiers: dict[str, str] = {}                 # nível → nome do modelo em uso (mostrado na Configuração)


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    emoji: str = Field(default="🤖", min_length=1, max_length=8)
    color: str = Field(default="#1F8A70", pattern=r"^#[0-9A-Fa-f]{6}$")
    persona: str = Field(default="", max_length=4000)


class AgentPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    emoji: str | None = Field(default=None, min_length=1, max_length=8)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    persona: str | None = Field(default=None, max_length=4000)


class Agent(AgentIn):
    id: UUID
    created_at: datetime
    documents: int = 0
    kind: Literal["agente", "consultor"] = "agente"
    ativo: bool = True                         # ficha de governança ativa (I4)
    nivel: str = "M1"                          # moderação vigente
    camada: int | None = None


class SheetOut(BaseModel):
    name: str
    columns: list[str]
    stored_rows: int
    total_rows: int


class Document(BaseModel):
    id: UUID
    filename: str
    mime: str
    size_bytes: int
    kind: Literal["pdf", "docx", "table", "text", "other"]
    status: Literal["pending", "ready", "unreadable", "failed"]
    pages: int | None
    note: str | None
    parts: int = 0
    sheets: list[SheetOut] = []
    agent_id: UUID | None
    conversation_id: UUID | None
    created_at: datetime
    origin: Literal["upload", "agent"] = "upload"
    purged: bool = False                       # espaço liberado pelo gerenciador: o arquivo não está mais guardado


class Step(BaseModel):
    icon: str
    text: str


class Message(BaseModel):
    id: UUID
    conversation_id: UUID
    seq: int
    author: Literal["user", "agent", "system"]
    agent_id: UUID | None
    agent_name: str | None
    body: str
    document: Document | None = None
    image_key: str | None
    run_id: UUID | None
    sources: list[str]
    steps: list[Step]
    error: str | None
    status: Literal["sent", "delivered", "read"] | None = None
    created_at: datetime
    card: dict[str, Any] | None = None         # pergunta rápida, confirmação ou cartão do parecer (renderizado pelo app, sem HTML)


class ConversationIn(BaseModel):
    kind: Literal["dm", "group"]
    agent_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=50)
    members: list[UUID] = Field(default_factory=list, max_length=20)
    emoji: str = Field(default="👥", min_length=1, max_length=8)
    color: str = Field(default="#5B6B8C", pattern=r"^#[0-9A-Fa-f]{6}$")


class ConversationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    members: list[UUID] | None = Field(default=None, min_length=1, max_length=20)


class Conversation(BaseModel):
    id: UUID
    kind: Literal["dm", "group"]
    agent_id: UUID | None
    name: str | None
    emoji: str
    color: str
    members: list[UUID]
    last_activity_at: datetime
    last_message: Message | None = None
    active_run: bool = False


class MessageIn(BaseModel):
    body: str = Field(default="", max_length=20000)
    document_id: UUID | None = None
    image_key: str | None = Field(default=None, max_length=300)


class Upload(BaseModel):
    kind: Literal["image", "document"]
    image_key: str | None = None
    document: Document | None = None


class RunEvent(BaseModel):
    at: datetime
    kind: str
    payload: dict[str, Any]


class Run(BaseModel):
    id: UUID
    conversation_id: UUID
    conversation_title: str
    agent_name: str
    status: str
    tier: str
    read_mode: str
    model: str
    input_tokens: int
    output_tokens: int
    tool_calls: int
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    events: list[RunEvent]
    chain_ok: bool


# ---- consumo e custos
class UsageDay(BaseModel):
    day: date
    input_tokens: int
    output_tokens: int
    cost_usd: float


class UsageModel(BaseModel):
    model: str
    label: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class UsageUser(BaseModel):
    user_id: UUID
    name: str
    email: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    today_tokens: int


class PriceOut(BaseModel):
    model: str = Field(pattern=r"^[a-z0-9.-]{3,80}$")
    label: str = Field(min_length=1, max_length=60)
    input_usd_mtok: float = Field(ge=0, le=1000)
    output_usd_mtok: float = Field(ge=0, le=1000)


class Usage(BaseModel):
    """Consumo de quem pergunta (ou de todos, no painel do administrador)."""
    days: list[UsageDay]
    by_model: list[UsageModel]
    total_tokens: int
    total_cost_usd: float
    today_tokens: int
    month_cost_usd: float
    daily_limit: int
    prices: list[PriceOut]


class AdminUsage(Usage):
    by_user: list[UsageUser]
    month_cost_all_usd: float
    monthly_budget_usd: float | None
    alert_pct: int


class ModelInfo(BaseModel):
    model: str
    label: str
    input_usd_mtok: float
    output_usd_mtok: float
    available: bool | None                     # None = a conta ainda não foi consultada (teste da chave)
    used_by: list[str] = []                    # níveis que usam este modelo agora


class ModelChoice(BaseModel):
    quick: str | None = Field(default=None, pattern=r"^[a-z0-9.-]{3,80}$")
    default: str | None = Field(default=None, pattern=r"^[a-z0-9.-]{3,80}$")
    complex: str | None = Field(default=None, pattern=r"^[a-z0-9.-]{3,80}$")
    router: str | None = Field(default=None, pattern=r"^[a-z0-9.-]{3,80}$")


class AiStatus(BaseModel):
    key_source: Literal["painel", "servidor", "nenhuma"]
    key_hint: str | None
    workspace_id: str | None
    secrets_ready: bool                        # o servidor tem SECRETS_KEY: dá para gravar chave pelo painel
    monthly_budget_usd: float | None
    alert_pct: int
    daily_token_limit: int | None              # None = padrão do servidor
    server_daily_limit: int
    month_cost_usd: float
    prices: list[PriceOut]
    models: dict[str, str] = {}                # nível → modelo em uso
    models_panel: ModelChoice = ModelChoice()  # o que foi escolhido no painel (vazio = .env)
    models_env: dict[str, str] = {}
    catalog: list[ModelInfo] = []
    models_checked_at: datetime | None = None


class AiConfigIn(BaseModel):
    workspace_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,80}$")
    monthly_budget_usd: float | None = Field(default=None, ge=0, le=1_000_000)
    alert_pct: int = Field(default=80, ge=1, le=100)
    daily_token_limit: int | None = Field(default=None, ge=0, le=1_000_000_000)


class KeyIn(BaseModel):
    api_key: str = Field(min_length=20, max_length=300, pattern=r"^sk-ant-[A-Za-z0-9_-]+$")
    workspace_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,80}$")


class KeyTest(BaseModel):
    ok: bool
    message: str
    detail: str | None = None
    model_tested: str | None = None
    models: list[str] = []


# ---- gerenciador de arquivos
class ManagedDocument(Document):
    place: Literal["agente", "conversa"]
    place_id: UUID
    place_name: str
    duplicates: int = 0                        # outros arquivos seus com o mesmo conteúdo (SHA-256)


class StorageGroup(BaseModel):
    key: str
    label: str
    files: int
    bytes: int


class StorageStats(BaseModel):
    files: int
    bytes: int
    quota_bytes: int | None
    freed_bytes: int
    by_kind: list[StorageGroup]
    by_place: list[StorageGroup]
    problems: int                              # falhou ou ilegível
    duplicate_groups: int
    duplicate_bytes: int                       # quanto sairia removendo as cópias


class StorageQuotaIn(BaseModel):
    storage_quota_mb: int | None = Field(default=None, ge=1, le=10_000_000)


# ---- skills
class SkillOut(BaseModel):
    id: UUID
    name: str
    description: str
    version: int
    enabled: bool
    shared: bool
    mine: bool
    size_bytes: int
    files: int
    agents: int = 0
    conversations: int = 0
    updated_at: datetime


class SkillDetail(SkillOut):
    body: str
    file_paths: list[str]


class SkillPatch(BaseModel):
    enabled: bool | None = None
    shared: bool | None = None


class SkillUploadResult(BaseModel):
    created: list[str]
    updated: list[str]
    ids: list[UUID] = []                       # todas as importadas (novas e atualizadas), para ativar em seguida


class SkillIds(BaseModel):
    skill_ids: list[UUID] = Field(default_factory=list, max_length=100)


class PreviewOut(BaseModel):
    name: str
    html: str                                  # página completa, para iframe sandbox (sem script)
    note: str | None = None


# ----------------------------------------------------------------- gestão de contas (multiusuário)
class AccountOut(BaseModel):
    id: str                                    # id do usuário no Keycloak
    username: str
    email: str | None
    name: str
    enabled: bool
    is_admin: bool
    is_master: bool
    created_at: datetime | None
    papo_id: UUID | None = None                # None = ainda não entrou no Papo
    conversations: int = 0
    agents: int = 0
    documents: int = 0
    bytes: int = 0
    month_cost_usd: float = 0.0
    last_activity: datetime | None = None
    must_change_password: bool = False


class AccountIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=320)
    name: str = Field(min_length=1, max_length=120)
    is_admin: bool = False


class AccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    is_admin: bool | None = None


class AccountSecret(BaseModel):
    account: AccountOut
    temp_password: str                         # mostrada uma vez; o usuário troca no primeiro acesso
