"""End-to-end orchestrations built on top of ``core``, ``llm_client``, and
``workbook``.

Each subpackage here wires those shared layers together for one concrete,
runnable job (export data, merge results, run a recurring review session). A
workflow may depend on ``core``/``llm_client``/`workbook``/``prompts``/``queries``,
but other workflows should not import each other except where one workflow
explicitly composes another (for example ``daily_review`` calling into
``salesforce_export`` and ``report_merge``).
"""
