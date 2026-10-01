import asyncio
import unittest

import backend


class BackendFallbackTests(unittest.TestCase):
    def test_hotel_agent_handles_tool_error(self):
        async def raise_error(_query):
            raise RuntimeError("429 rate limit from Tavily")

        original = backend.tavily_mcp_search
        backend.tavily_mcp_search = raise_error
        try:
            async def run():
                return await backend.hotel_agent({"user_query": "Tokyo trip", "llm_calls": 0})

            result = asyncio.run(run())
            self.assertIn("Hotel information unavailable", result["hotel_results"])
        finally:
            backend.tavily_mcp_search = original

    def test_weather_agent_handles_tool_error(self):
        async def raise_error(_city):
            raise RuntimeError("Weather API outage")

        original_weather = backend.weather_mcp_search
        original_forecast = backend.forecast_mcp_search
        backend.weather_mcp_search = raise_error
        backend.forecast_mcp_search = raise_error
        try:
            async def run():
                return await backend.weather_agent({"user_query": "Tokyo trip", "llm_calls": 0})

            result = asyncio.run(run())
            self.assertIn("Weather information unavailable", result["weather_results"])
        finally:
            backend.weather_mcp_search = original_weather
            backend.forecast_mcp_search = original_forecast


if __name__ == "__main__":
    unittest.main()
