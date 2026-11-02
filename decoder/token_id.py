from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Union


class TokenKind(Enum):
    NEP141 = auto()
    NEP171 = auto()
    NEP245 = auto()
    IMT = auto()


@dataclass(frozen=True)
class Nep141TokenId:
    contract_id: str
    kind: TokenKind = TokenKind.NEP141

    def __str__(self) -> str:
        return f"nep141:{self.contract_id}"


@dataclass(frozen=True)
class Nep171TokenId:
    contract_id: str
    token_id: str
    kind: TokenKind = TokenKind.NEP171

    def __str__(self) -> str:
        return f"nep171:{self.contract_id}:{self.token_id}"


@dataclass(frozen=True)
class Nep245TokenId:
    contract_id: str
    mt_token_id: str
    kind: TokenKind = TokenKind.NEP245

    def __str__(self) -> str:
        return f"nep245:{self.contract_id}:{self.mt_token_id}"


@dataclass(frozen=True)
class ImtTokenId:
    contract_id: str
    token_id: str
    kind: TokenKind = TokenKind.IMT

    def __str__(self) -> str:
        return f"imt:{self.contract_id}:{self.token_id}"


TokenId = Union[Nep141TokenId, Nep171TokenId, Nep245TokenId, ImtTokenId]

_PREFIX_NTYPE = {
    "nep141": TokenKind.NEP141,
    "nep171": TokenKind.NEP171,
    "nep245": TokenKind.NEP245,
    "imt": TokenKind.IMT,
}

_POA_CONTRACT_RE = re.compile(r"^[^.]+\.omft\.near$")
_HOT_CONTRACT_RE = re.compile(
    r"^nep245:v2(?:_\d+)?\.omni\.hot\.tg:<([^>]+)>_(.+)$"
)


def parse_token_id(raw: str) -> TokenId:
    first_colon = raw.find(":")
    if first_colon == -1:
        raise ValueError(f"TokenId missing prefix separator: {raw!r}")

    prefix = raw[:first_colon]
    rest = raw[first_colon + 1 :]

    if prefix not in _PREFIX_NTYPE:
        raise ValueError(f"Unknown TokenId prefix {prefix!r} in {raw!r}")

    kind = _PREFIX_NTYPE[prefix]

    if kind == TokenKind.NEP141:
        return Nep141TokenId(contract_id=rest)

    second_colon = rest.find(":")
    if second_colon == -1:
        raise ValueError(f"TokenId {prefix!r} missing second separator in {raw!r}")

    contract_id = rest[:second_colon]
    sub_id = rest[second_colon + 1 :]

    if kind == TokenKind.NEP171:
        return Nep171TokenId(contract_id=contract_id, token_id=sub_id)
    if kind == TokenKind.NEP245:
        return Nep245TokenId(contract_id=contract_id, mt_token_id=sub_id)
    return ImtTokenId(contract_id=contract_id, token_id=sub_id)


_CHAIN_BY_OMFT_CONTRACT: dict[str, str] = {}

_HOT_CHAIN_PREFIX_MAP: dict[str, str] = {
    "eth": "ethereum",
    "base": "base",
    "arb": "arbitrum",
    "bnb": "bnb",
    "sol": "solana",
    "near": "near",
    "ton": "ton",
    "btc": "bitcoin",
    "doge": "doge",
    "trx": "tron",
    "xrp": "xrp",
}


def origin_chain(token: TokenId) -> str | None:
    if isinstance(token, Nep141TokenId):
        if token.contract_id == "wrap.near":
            return "near"
        if _POA_CONTRACT_RE.match(token.contract_id):
            bridge_prefix = token.contract_id.split(".")[0]
            return _CHAIN_BY_OMFT_CONTRACT.get(bridge_prefix)
        return None

    if isinstance(token, Nep245TokenId):
        mt = token.mt_token_id
        if mt.startswith("nep141:"):
            for chain_prefix, chain_name in _HOT_CHAIN_PREFIX_MAP.items():
                if mt.startswith(f"nep141:{chain_prefix}_") or mt.startswith(
                    f"nep141:0x"
                ):
                    pass
            chain_prefix = mt.split(":")[1].split("_")[0] if ":" in mt else None
            if chain_prefix:
                return _HOT_CHAIN_PREFIX_MAP.get(chain_prefix)
        return None

    return None
