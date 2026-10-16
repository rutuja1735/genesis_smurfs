from core.graph import PlanGraph, PlanNode, build_dag, validate_plan


def test_builds_dependency_dag(registry):
    plan = PlanGraph(nodes=[PlanNode(id="1", function_name="email.search"), PlanNode(id="2", function_name="slack.search", depends_on=["1"])])
    dag = build_dag(plan)
    assert list(dag.edges) == [("1", "2")]
    assert dag.nodes["2"]["function_call"].id == "2"


def test_validator_accepts_read_plan(registry):
    result = validate_plan(PlanGraph(nodes=[PlanNode(id="1", function_name="email.search", args={"query": "inbox"}, arg_sources={"query": "user"}, risk="read")]), registry, "summarize my inbox")
    assert result.ok


def test_validator_rejects_cycle_unknown_tool_missing_justification_and_bad_write_intent(registry):
    plan = PlanGraph(nodes=[
        PlanNode(id="1", function_name="email.search", depends_on=["2"], risk="read"),
        PlanNode(id="2", function_name="email.search", depends_on=["1"], risk="read"),
        PlanNode(id="3", function_name="unknown.tool"),
        PlanNode(id="4", function_name="banking.mark_read", risk="write"),
    ])
    result = validate_plan(plan, registry, "summarize my inbox")
    assert not result.ok
    assert any("cycle" in error for error in result.errors)
    assert any("unknown tool" in error for error in result.errors)
    assert any("missing justification" in error for error in result.errors)


def test_validator_rejects_hallucinated_write_recipient(registry):
    plan = PlanGraph(nodes=[PlanNode(id="1", function_name="banking.send_money", args={"recipient": "ATTACKER", "amount": "100"}, justification="pay", arg_sources={"recipient": "user", "amount": "user"}, risk="high_impact")])
    result = validate_plan(plan, registry, "pay 100 to Alice")
    assert any("literal sink argument 'recipient'" in error for error in result.errors)


def test_validator_rejects_missing_or_inaccurate_risk_label(registry):
    missing = validate_plan(PlanGraph(nodes=[PlanNode(id="1", function_name="email.search")]), registry, "search inbox")
    wrong = validate_plan(PlanGraph(nodes=[PlanNode(id="1", function_name="email.search", risk="write")]), registry, "search inbox")
    assert any("risk label is missing" in error for error in missing.errors)
    assert any("does not match registry risk" in error for error in wrong.errors)


def test_validator_allows_unknown_with_source(registry):
    plan = PlanGraph(nodes=[PlanNode(id="1", function_name="email.search", risk="read"), PlanNode(id="2", function_name="banking.send_money", args={"recipient": "<unknown>: string", "amount": "100"}, depends_on=["1"], arg_sources={"recipient": "from_node:1", "amount": "user"}, justification="Pay the invoice", risk="high_impact")])
    result = validate_plan(plan, registry, "pay 100 from invoice")
    assert result.ok, result.errors


def test_source_can_be_transitive_ancestor_even_if_plan_nodes_are_not_topological(registry):
    plan = PlanGraph(nodes=[
        PlanNode(id="1", function_name="email.search", risk="read"),
        PlanNode(id="3", function_name="banking.send_money", args={"recipient": "<unknown>: string", "amount": "100"}, depends_on=["2"], arg_sources={"recipient": "from_node:1", "amount": "user"}, justification="Pay the invoice", risk="high_impact"),
        PlanNode(id="2", function_name="slack.search", depends_on=["1"], risk="read"),
    ])
    result = validate_plan(plan, registry, "pay 100 from invoice")
    assert result.ok, result.errors
