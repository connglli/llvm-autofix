import random
import tempfile
from pathlib import Path

from harness.lms.agent import AgentConfig, AgentHooks
from harness.lms.skill import SKILL_FILE
from harness.lms.tool import (
  FuncToolCallException,
  FuncToolSpec,
  StatelessFuncToolBase,
)


class GetWeather(StatelessFuncToolBase):
  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "get_weather",
      "Fetch the current weather (weather, temperature, wind speed, etc) for a specified location at a specified date with a specified unit.",
      [
        FuncToolSpec.Param(
          "location", "string", True, "The name of the location to get the weather for."
        ),
        FuncToolSpec.Param(
          "date",
          "string",
          True,
          "The date to get the weather for in the format on YYYY-mm-dd.",
        ),
        FuncToolSpec.Param(
          "celsius",
          "bool",
          True,
          "Whether to use Celsius (True) or Fahrenheit (False) for the temperature.",
        ),
      ],
      [],
    )

  def _call(self, *, location, date, celsius, **kwargs) -> str:
    temperature = {
      # European cities
      "Zurich": 19,
      "London": 18,
      "Paris": 20,
      "Berlin": 21,
      "Madrid": 22,
      # American cities
      "New York": 25,
      "Los Angeles": 28,
      "Chicago": 24,
      "Miami": 30,
      "Houston": 29,
      "Toronto": 23,
      # Asian cities
      "Beijing": 26,
      "Shanghai": 27,
      "Chongqing": 29,
      "Hong Kong": 31,
      "Macau": 30,
      "Chinese Taipei": 28,
      "Tokyo": 22,
      "Seoul": 21,
      "Singapore": 30,
      "Mumbai": 32,
      # Australian cities
      "Sydney": 23,
      "Melbourne": 21,
      "Brisbane": 29,
      "Perth": 26,
    }.get(location, None)
    if temperature is None:
      raise FuncToolCallException("Unknown location " + location)
    if celsius:
      temperature = f"{temperature}°C"
    else:
      temperature = f"{temperature * 9 / 5 + 32}°F"
    weather = ["Sunny", "Cloudy", "Rainy", "Windy", "Stormy"][random.randint(0, 10) % 5]
    air_quality = ["Good", "Fair", "Bad", "Extremely Bad"][random.randint(0, 10) % 4]
    wind_speed = random.randint(5, 20)  # km/h
    humidity = random.randint(30, 90)  # percentage
    return f"""\
Location: {location}
Date: {date}
Weather: {weather}
Temperature: {temperature}
Air Quality: {air_quality}
Wind Speed: {wind_speed} km/h
Humidity: {humidity}%"""


class GetAverage(StatelessFuncToolBase):
  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "get_average",
      "Calculate the average of a list of numbers.",
      [
        FuncToolSpec.Param(
          "numbers", "list[int|float]", True, "A list of numbers to sum up."
        )
      ],
      [],
    )

  def _call(self, *, numbers: list, **kwargs) -> str:
    if not isinstance(numbers, list):
      raise FuncToolCallException(
        f"The 'numbers' parameter must be a list, {type(numbers)} is given."
      )
    try:
      return str(sum(numbers) / len(numbers))
    except TypeError as e:
      raise FuncToolCallException(
        f"Elements of the 'numbers' list must be either integer or float: {e}"
      )


class FinishTask(StatelessFuncToolBase):
  def spec(self) -> FuncToolSpec:
    return FuncToolSpec(
      "finish",
      "When you have solved the user's issue, call this tool to let users know you're finished and present your result.",
      [
        FuncToolSpec.Param(
          "result", "string", True, "The final result presenting to the user."
        )
      ],
      [],
    )

  def _call(self, *, result: str, **kwargs) -> str:
    return result


def test_weather(config: AgentConfig):
  """Demo: tools only — agent uses get_weather + get_average directly."""
  lm = config.create_agent(
    tools=[(GetWeather(), 100), (GetAverage(), 100), (FinishTask(), 1)],
  )
  lm.console.print(f"Using model: {lm.model}")

  lm.append_user_message(
    "Please calculate the average temperature of all *European* cities shown below: New York, Beijing, Zurich, Chongqing, London, Berlin, Toronto, Shanghai, Seoul."
  )

  lm.run(
    AgentHooks(
      post_response=lambda x: (
        True,
        "Error: You're NOT calling any tool or you called with an INCORRECT format. Always select a tool to call with correct Tool Call Format. If you're done with the task, call the 'finish' tool with the result.",
      ),
      post_tool_call=lambda tool, args, res: (
        tool != "finish",
        f"Good. The model gives the result: {res}" if tool == "finish" else res,
      ),
    ),
  )


def test_skill(config: AgentConfig):
  """Demo: skills — agent delegates to weather_report skill."""

  weather_report = """\
---
name: weather-report
description: Fetch weather for all cities in a given region and produce a summary report
parameters:
  - name: region
    type: string
    required: true
    description: The region name (e.g. "European", "Asian") to filter cities
  - name: date
    type: string
    required: true
    description: The date in YYYY-mm-dd format
allowed-tools: [get_weather]
tool-budget: 20
context: fork
---

You are a weather analyst. Your task is to produce a summary weather report.

**Region**: {{ region }}
**Date**: {{ date }}

Steps:
1. Use the `get_weather` tool to fetch weather for each city in the requested region (use Celsius).
2. After collecting all data, compile a brief report listing each city's weather, temperature, and conditions.
3. Include the average temperature across all cities.
4. Call `skill_done` with the full report text.
"""
  # Write weather_report skill into a temporary directory for loading
  with tempfile.TemporaryDirectory() as tmpdir:
    skill_dir = Path(tmpdir) / "weather-report"
    skill_dir.mkdir()
    (skill_dir / SKILL_FILE).write_text(weather_report)

    lm = config.create_agent(
      tools=[(GetWeather(), 100), (GetAverage(), 100), (FinishTask(), 1)],
      skills=[
        (skill_dir, 1, 5)
      ],  # Allow the skill to be called once, and each tool inside the skill can be called up to 5 times
    )
    lm.console.print(f"Using model: {lm.model}")

    lm.append_user_message(
      "Give me a weather report for all European cities for 2026-03-17. "
      "Prefer weather-report to get_weather."
    )

    lm.run(
      AgentHooks(
        post_response=lambda x: (
          True,
          "Error: You're NOT calling any tool or you called with an INCORRECT format. Always select a tool to call with correct Tool Call Format. If you're done with the task, call the 'finish' tool with the result.",
        ),
        post_tool_call=lambda tool, args, res: (
          tool != "finish",
          f"Good. The model gives the result: {res}" if tool == "finish" else res,
        ),
      ),
    )


if __name__ == "__main__":
  from argparse import ArgumentParser

  parser = ArgumentParser(description="Demo for agent tools and skills.")
  parser.add_argument("demo", choices=["weather", "skill"], help="Which demo to run.")
  parser.add_argument(
    "--model", "-m", default="gpt-4.1-mini", help="Model name (default: gpt-4.1-mini)."
  )
  parser.add_argument(
    "--driver",
    "-D",
    choices=["openai", "anthropic"],
    default="openai",
    help="LLM API driver (default: openai).",
  )
  args = parser.parse_args()

  if args.driver == "openai":
    from harness.lms.openai_generic import GPTGenericAgent

    driver_class = GPTGenericAgent
  elif args.driver == "anthropic":
    from harness.lms.anthropic_generic import ClaudeGenericAgent

    driver_class = ClaudeGenericAgent

  config = AgentConfig(
    driver_class=driver_class,
    model=args.model,
    debug_mode=True,
  )

  if args.demo == "weather":
    test_weather(config)
  elif args.demo == "skill":
    test_skill(config)
