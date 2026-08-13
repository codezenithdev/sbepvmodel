import unittest

from sbepv.agent.prompts import SOLAR_AGENT_INSTRUCTIONS
from sbepv.agent.tool_schemas import SCENARIO_TOOL


class AgentAnnualIntervalContractTests(unittest.TestCase):
    def test_prompt_excludes_coarse_annual_intervals(self) -> None:
        self.assertIn(
            "the only supported hour interval is 1 hour",
            SOLAR_AGENT_INSTRUCTIONS,
        )
        self.assertIn(
            "Coarser hour and day intervals are rejected",
            SOLAR_AGENT_INSTRUCTIONS,
        )
        self.assertNotIn("1 day is also supported", SOLAR_AGENT_INSTRUCTIONS)

    def test_scenario_tool_documents_safe_annual_interval(self) -> None:
        properties = SCENARIO_TOOL["parameters"]["properties"]
        value_description = properties["interval_value"]["description"]
        unit_description = properties["interval_unit"]["description"]

        self.assertIn("only supported hour value is 1", value_description)
        self.assertIn("day intervals are not supported", value_description)
        self.assertIn("Day intervals are not supported", unit_description)


if __name__ == "__main__":
    unittest.main()
