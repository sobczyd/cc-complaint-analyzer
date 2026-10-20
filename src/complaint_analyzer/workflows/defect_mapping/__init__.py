"""Map complaints to existing Jira defects and RCAs, after clustering.

Three pieces, all reusable across runs:

* ``jira`` - a corpus of NC defects and RCA issues (fetched by an agent, normalized here),
* ``kb`` - the Confluence KB articles the complaint qualifications cite,
* ``mapping`` - the sub-cluster batches, candidate filtering, validation and final mapping.
"""

from __future__ import annotations

from .jira import JiraCorpusError
from .kb import KbCorpusError
from .mapping import MappingError

__all__ = ["JiraCorpusError", "KbCorpusError", "MappingError"]
