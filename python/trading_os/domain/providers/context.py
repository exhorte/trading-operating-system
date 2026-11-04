"""What the Risk Engine is told about the provider side of an account, gathered by the services (ADR 0036).

One value per question the contract raises. A field left ``None`` means the question does not apply to this evaluation (no symbol
under review, no rule on this product) — never « answered yes ». Every field that *does* arrive can refuse an entry; none of them can
allow one the personal rules refuse: the provider's rules only ever add reasons.
"""

from __future__ import annotations

from trading_os.domain.primitives import DomainModel
from trading_os.domain.providers.identity import AccountIdentification
from trading_os.domain.providers.loss_floors import ProviderLossState
from trading_os.domain.providers.restrictions import NewsDecision, OvernightDecision, RequestBudget
from trading_os.domain.providers.rules import ProviderRuleSet


class ProviderContext(DomainModel):
    identification: AccountIdentification
    rule_set: ProviderRuleSet | None = None
    loss: ProviderLossState | None = None
    news: NewsDecision | None = None
    overnight: OvernightDecision | None = None
    requests: RequestBudget | None = None


__all__ = ["ProviderContext"]
