import os
from openai import AzureOpenAI
from bs4 import BeautifulSoup
import json
import logging
import asyncio
from playwright.async_api import async_playwright
import time

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('agent.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize Azure OpenAI client
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version="2023-03-15-preview",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)

class SwarmAgent:
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.logger = logging.getLogger(f"{__name__}.{name}")

    def run(self, input_data: str) -> dict:
        """Base run method to be overridden by specific agents"""
        raise NotImplementedError

class HTMLAgent(SwarmAgent):
    def __init__(self):
        super().__init__(
            name="HTML Parser",
            description="Extract clean text from HTML content"
        )

    def run(self, html_content: str) -> dict:
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            for element in soup(['script', 'style']):
                element.decompose()
            
            text_content = ""
            for tag in soup.find_all():
                if tag.name == 'script':
                    continue
                if tag.name and tag.string:
                    text_content += f"{tag.name.upper()}: {tag.string.strip()}\n"
                elif tag.string:
                    text_content += f"{tag.string.strip()}\n"
            text_content = text_content.strip()

            return {"success": True, "data": text_content}
        except Exception as e:
            self.logger.error(f"HTML parsing error: {str(e)}")
            return {"success": False, "error": str(e)}

class GPTAgent(SwarmAgent):
    def __init__(self):
        super().__init__(
            name="GPT Parser",
            description="Parse text into structured event data using GPT-4"
        )

    def run(self, text_content: str) -> dict:
        try:
            system_message = """Extract event information from the text and return it as JSON with this structure:
[{
    "title": str,
    "date": str (YYYY-MM-DD),
    "time": str (HH:MM),
    "venue": {"name": str, "address": str},
    "ticket_prices": {"category": price},
    "performers": ["performer1", "performer2"],
    "additional_info": "optional additional information"
}]
Only return the JSON object, no other text."""

            response = client.chat.completions.create(
                model="gpt-35-turbo",
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": text_content}
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )

            parsed_json = json.loads(response.choices[0].message.content)
            return {"success": True, "data": parsed_json}
        except Exception as e:
            self.logger.error(f"GPT parsing error: {str(e)}")
            return {"success": False, "error": str(e)}

class PlaywrightAgent(SwarmAgent):
    def __init__(self):
        super().__init__(
            name="Playwright Agent",
            description="Execute JavaScript and scrape Ticketmaster events"
        )

    async def _run_playwright(self, search_query: str = "techno") -> dict:
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=False)
                page = await browser.new_page()
                
                self.logger.info("Navigating to Ticketmaster")
                await page.goto('https://www.ticketmaster.com/')
                
                self.logger.info(f"Searching for: {search_query}")
                await page.wait_for_selector('#searchFormInput-input')
                await page.click('#searchFormInput-input')
                await page.fill('#searchFormInput-input', search_query)
                await page.keyboard.press('Enter')
                
                self.logger.info("Waiting for results")
                await page.wait_for_timeout(3000)
                
                content = await page.content()
                await browser.close()
                return {"success": True, "data": content}
        except Exception as e:
            self.logger.error(f"Playwright execution error: {str(e)}")
            return {"success": False, "error": str(e)}

    def run(self, search_query: str = "techno") -> dict:
        try:
            return asyncio.run(self._run_playwright(search_query))
        except Exception as e:
            self.logger.error(f"Playwright agent error: {str(e)}")
            return {"success": False, "error": str(e)}

class Orchestrator:
    def __init__(self):
        self.playwright_agent = PlaywrightAgent()
        self.html_agent = HTMLAgent()
        self.gpt_agent = GPTAgent()
        self.logger = logging.getLogger(f"{__name__}.Orchestrator")

    def process_event(self, search_query: str = "techno") -> dict:
        try:
            # 1. Scrape Ticketmaster using Playwright
            self.logger.info("Scraping Ticketmaster with Playwright")
            playwright_result = self.playwright_agent.run(search_query)
            if not playwright_result["success"]:
                return {"success": False, "error": playwright_result["error"]}

            # 2. Extract text using HTML agent directly from playwright result
            self.logger.info("Extracting text from HTML")
            html_result = self.html_agent.run(playwright_result["data"])
            if not html_result["success"]:
                return {"success": False, "error": html_result["error"]}

            # 3. Parse text using GPT agent
            self.logger.info("Parsing text with GPT-4")
            gpt_result = self.gpt_agent.run(html_result["data"])
            if not gpt_result["success"]:
                return {"success": False, "error": gpt_result["error"]}

            # 4. Save the final results
            event_data = gpt_result["data"]
            with open('events.json', 'w', encoding='utf-8') as f:
                json.dump(event_data, f, indent=2)
            
            self.logger.info("Successfully saved results to events.json")
            return {"success": True, "data": event_data}

        except Exception as e:
            self.logger.error(f"Orchestration error: {str(e)}")
            return {"success": False, "error": str(e)}

def main() -> dict:
    """Main function to process the event page"""
    import argparse

    query = input("Enter search query for events (default: techno): ").strip()
    if not query:
        query = "techno"
    args = type('Args', (), {'query': query})()

    orchestrator = Orchestrator()
    result = orchestrator.process_event(args.query)
    return result["data"] if result["success"] else {"error": result["error"]}

if __name__ == "__main__":
    main()
