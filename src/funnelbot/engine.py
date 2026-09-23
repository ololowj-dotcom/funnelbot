from __future__ import annotations

from .builder_ui import BuilderMixin
from .flow import FlowMixin


class Engine(BuilderMixin, FlowMixin):
    pass
