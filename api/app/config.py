"""Configuração por variável de ambiente. Nada de segredo em código."""
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["production", "staging", "development", "test"] = "production"
    database_url: str = Field(description="postgresql+asyncpg://papo_app:...@postgres:5432/papo")
    redis_url: str = "redis://redis:6379/0"

    # Keycloak / OIDC
    oidc_issuer: str = ""                       # https://auth.exemplo.com/realms/papo
    oidc_audience: str = "papo-api"
    oidc_jwks_url: str = ""                     # vazio → {issuer}/protocol/openid-connect/certs
    auth_dev_mode: bool = False                 # aceita X-Dev-User; PROIBIDO fora de development/test

    # MinIO / S3
    s3_endpoint: str = "minio:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "papo"
    s3_secure: bool = False
    storage_dir: str = ""                       # dev/test: grava em disco em vez do MinIO
    llm_provider: Literal["anthropic", "echo"] = "anthropic"   # echo só em development/test

    # Anthropic — IDs fixos (snapshots); troca de modelo é mudança revisada
    anthropic_api_key: str = ""                 # padrão do servidor; a chave cadastrada no painel tem prioridade
    anthropic_workspace_id: str = ""            # exigido por chaves que não são de um workspace só
    secrets_key: str = ""                       # cifra a chave guardada no banco (AES-GCM); sem ela o painel não grava chave
    hubgw_url: str = "http://hubgw:8200"         # gateway de leitura do hub (único com acesso às fontes)
    hubgw_token: str = ""
    hubgw_local_roots: str = ""                   # no gateway: "opt=/hub/opt,www=/hub/www" (pastas desta VPS montadas :ro)
    admin_role: str = "papo-admin"              # papel do realm no Keycloak que abre a área de administração
    dev_admins: list[str] = ["admin"]           # development/test: usuários de teste tratados como administradores
    master_role: str = "papo-master"            # papel do master: único que promove ou rebaixa administradores
    dev_masters: list[str] = ["master"]         # development/test: usuários de teste tratados como master
    # Gestão de contas: cliente confidencial do realm com service account (view-users, query-users, manage-users)
    kc_internal_url: str = "http://keycloak:8080/auth"
    kc_realm: str = "papo"
    kc_admin_client_id: str = "papo-users"
    kc_admin_client_secret: str = ""
    model_quick: str = "claude-haiku-4-5-20251001"
    model_default: str = "claude-sonnet-5-5"
    model_complex: str = "claude-opus-5-5"
    model_router: str = "claude-haiku-4-5-20251001"
    max_tool_turns: int = Field(default=8, ge=1, le=16)
    max_output_tokens: int = Field(default=8000, ge=256, le=16000)   # o raciocínio também consome daqui

    # Limites
    max_upload_mb: int = Field(default=50, ge=1, le=50)
    daily_token_limit: int = Field(default=2_000_000, ge=0)   # 0 = sem limite
    messages_per_minute: int = Field(default=20, ge=1)
    cors_origins: list[str] = []

    @model_validator(mode="after")
    def _guard(self) -> "Settings":
        if self.auth_dev_mode and self.env not in ("development", "test"):
            raise ValueError("AUTH_DEV_MODE só é permitido em development/test")
        if (self.storage_dir or self.llm_provider == "echo") and self.env not in ("development", "test"):
            raise ValueError("STORAGE_DIR e LLM_PROVIDER=echo só são permitidos em development/test")
        if self.env == "production":
            # sem ANTHROPIC_API_KEY o app sobe e funciona; só as respostas dos agentes avisam que a IA não está configurada
            missing = [k for k in ("oidc_issuer", "s3_access_key", "s3_secret_key") if not getattr(self, k)]
            if missing:
                raise ValueError(f"variáveis obrigatórias ausentes em produção: {', '.join(missing).upper()}")
        return self

    def model_for(self, tier: str) -> str:
        return {"quick": self.model_quick, "complex": self.model_complex}.get(tier, self.model_default)

    @property
    def jwks_url(self) -> str:
        return self.oidc_jwks_url or f"{self.oidc_issuer.rstrip('/')}/protocol/openid-connect/certs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
