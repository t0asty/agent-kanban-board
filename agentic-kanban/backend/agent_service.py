import asyncio
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional

from google import genai
from google.genai import types

from agent_interaction_log import (
    json_preview,
    log_generate_cards_end,
    log_generate_cards_llm_request,
    log_generate_cards_prompt_full,
    log_generate_cards_response,
    log_generate_cards_start,
    log_generate_cards_tool,
)
from workspace_fs import workspace_list, workspace_read, workspace_write

logger = logging.getLogger(__name__)

class AgentService:
    """Service for interacting with the MCP agent to generate kanban cards"""
    
    def __init__(self):
        self.gemini_api_key = os.getenv("GOOGLE_API_KEY")
        self.model_name = "gemini-2.5-flash-lite"
        if self.gemini_api_key:
            self.client = genai.Client(api_key=self.gemini_api_key)
            # Keep self.model for compatibility with existing readiness checks.
            self.model = self.model_name
            logger.info("AgentService initialized with Gemini model: %s", self.model_name)
        else:
            self.client = None
            self.model = None
            logger.warning("No Gemini API key found, will use fallback generation")
    
    async def generate_cards_from_prompt(
        self, prompt: str, workspace_path: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate kanban cards from a user prompt using Gemini AI or fallback logic
        
        Args:
            prompt: User's project description
            
        Returns:
            List of card dictionaries ready for creation
        """
        workspace_root: Optional[Path] = None
        if workspace_path:
            try:
                wp = Path(workspace_path).expanduser().resolve()
                if wp.is_dir():
                    workspace_root = wp
            except OSError as e:
                logger.warning("Invalid workspace path %r: %s", workspace_path, e)

        logger.debug(
            "generate_cards_from_prompt called (prompt_length=%d, model_configured=%s, workspace=%s)",
            len(prompt),
            bool(self.model and self.gemini_api_key),
            str(workspace_root) if workspace_root else None,
        )
        if self.model and self.gemini_api_key:
            logger.info("Using Gemini agent generation path")
            try:
                return await self._generate_cards_with_gemini(prompt, workspace_root=workspace_root)
            except Exception as e:
                logger.error(f"Gemini generation failed: {e}")
                # Fall back to basic generation
                logger.warning("Falling back to keyword-based generation after Gemini failure")
                return self._generate_fallback_cards(prompt)
        else:
            logger.info("Using fallback generation path (Gemini not configured)")
            return self._generate_fallback_cards(prompt)
    
    def _parse_cards_json_text(self, text: str) -> List[Dict[str, Any]]:
        """Parse model output into a list of card dicts; supports raw JSON or fenced blocks."""
        raw = (text or "").strip()
        if not raw:
            return []

        candidates = [raw]
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
        if fence:
            candidates.insert(0, fence.group(1).strip())
        bracket = re.search(r"\[[\s\S]*\]", raw)
        if bracket:
            candidates.append(bracket.group(0).strip())

        for candidate in candidates:
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(data, list):
                return data
        raise json.JSONDecodeError("No JSON array of cards found", raw, 0)

    async def _generate_cards_with_gemini(
        self, prompt: str, workspace_root: Optional[Path] = None
    ) -> List[Dict[str, Any]]:
        """Generate cards using Gemini AI, optionally with workspace file tools."""
        run_id = f"gen-{uuid.uuid4().hex[:12]}"
        logger.debug(
            "Sending prompt to Gemini (prompt_length=%d, workspace=%s)",
            len(prompt),
            str(workspace_root) if workspace_root else None,
        )
        log_generate_cards_start(
            run_id=run_id,
            model=self.model_name,
            prompt_chars=len(prompt),
            workspace=str(workspace_root) if workspace_root else None,
            max_tool_rounds=24 if workspace_root is not None else None,
        )

        base_instructions = """You are a kanban board task generator. Given a user's project description, generate a list of kanban cards (tasks).

Each card must have:
- title: A clear, concise task title
- description: A detailed description of what needs to be done
- status: One of "research", "in-progress", "done", "blocked", or "planned"
- order: Sequential number starting from 1
- tags: Array of relevant tags (3-5 tags per card)

Generate 5-8 relevant tasks based on the user's input."""

        if workspace_root is not None:
            root_display = str(workspace_root)
            gemini_prompt = f"""{base_instructions}

The user's project folder on this machine (sandboxed for your tools) is:
{root_display}

You have tools to list directories, read files, and write files under that folder only. Use them when inspecting the codebase, writing plans, reports, or scaffolding files would help produce better tasks.

When you are completely done (including after any tool use), respond with ONLY a valid JSON array of card objects. No markdown fences, no explanation before or after the array.

User input: {prompt}
"""
            root = workspace_root.resolve()

            def list_workspace_directory(relative_path: str = ".") -> str:
                """List files and subdirectories under a path relative to the workspace root.

                Args:
                    relative_path: Directory relative to workspace (default: root). Use "." for the workspace root.
                """
                t0 = time.perf_counter()
                try:
                    out = workspace_list(root, relative_path)
                except Exception as e:
                    logger.exception("generate_cards list_workspace_directory")
                    out = json.dumps({"error": str(e)})
                log_generate_cards_tool(
                    run_id=run_id,
                    tool="list_workspace_directory",
                    arguments_summary=json_preview({"relative_path": relative_path}),
                    result=out,
                    duration_ms=(time.perf_counter() - t0) * 1000,
                )
                return out

            def read_workspace_file(relative_path: str) -> str:
                """Read a text file under the workspace. Path is relative to the workspace root.

                Args:
                    relative_path: File path relative to workspace (e.g. "README.md", "src/app.ts").
                """
                t0 = time.perf_counter()
                try:
                    out = workspace_read(root, relative_path)
                except Exception as e:
                    logger.exception("generate_cards read_workspace_file")
                    out = json.dumps({"error": str(e)})
                log_generate_cards_tool(
                    run_id=run_id,
                    tool="read_workspace_file",
                    arguments_summary=json_preview({"relative_path": relative_path}),
                    result=out,
                    duration_ms=(time.perf_counter() - t0) * 1000,
                )
                return out

            def write_workspace_file(relative_path: str, content: str) -> str:
                """Create or overwrite a text file under the workspace. Creates parent folders if needed.

                Args:
                    relative_path: File path relative to workspace.
                    content: Full file contents (UTF-8 text).
                """
                t0 = time.perf_counter()
                try:
                    out = workspace_write(root, relative_path, content)
                except Exception as e:
                    logger.exception("generate_cards write_workspace_file")
                    out = json.dumps({"error": str(e)})
                log_generate_cards_tool(
                    run_id=run_id,
                    tool="write_workspace_file",
                    arguments_summary=json_preview(
                        {"relative_path": relative_path, "content_chars": len(content or "")}
                    ),
                    result=out,
                    duration_ms=(time.perf_counter() - t0) * 1000,
                )
                return out

            tools = [
                list_workspace_directory,
                read_workspace_file,
                write_workspace_file,
            ]
            config = types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=8192,
                tools=tools,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    maximum_remote_calls=24,
                ),
            )
        else:
            gemini_prompt = f"""{base_instructions}

Return ONLY a valid JSON array of cards, no additional text.

User input: {prompt}

Return JSON array:"""
            config = types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=2048,
                response_mime_type="application/json",
            )

        tool_names = (
            [getattr(t, "__name__", repr(t)) for t in tools]
            if workspace_root is not None
            else []
        )
        log_generate_cards_llm_request(
            run_id=run_id,
            model=self.model_name,
            prompt_chars=len(gemini_prompt),
            tool_names=tool_names,
        )
        log_generate_cards_prompt_full(run_id=run_id, prompt=gemini_prompt)

        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model_name,
                contents=gemini_prompt,
                config=config,
            )

            if response.text:
                logger.debug("Received non-empty response from Gemini")
                try:
                    cards_data = self._parse_cards_json_text(response.text)
                    formatted_cards = self._format_cards(cards_data)
                except json.JSONDecodeError as e:
                    log_generate_cards_response(
                        run_id=run_id, response_text=response.text, num_cards=0
                    )
                    log_generate_cards_end(
                        run_id=run_id, outcome="parse_json_failed", detail=str(e)
                    )
                    logger.error("Failed to parse Gemini JSON response: %s", e)
                    logger.warning(
                        "Falling back to keyword-based generation due to JSON parsing failure"
                    )
                    return self._generate_fallback_cards(prompt)
                log_generate_cards_response(
                    run_id=run_id,
                    response_text=response.text,
                    num_cards=len(formatted_cards),
                )
                log_generate_cards_end(
                    run_id=run_id,
                    outcome="success",
                    detail=f"{len(formatted_cards)} cards",
                )
                logger.info("Gemini generation succeeded with %d cards", len(formatted_cards))
                return formatted_cards
            logger.warning("Empty response from Gemini")
            log_generate_cards_response(run_id=run_id, response_text=None, num_cards=0)
            log_generate_cards_end(run_id=run_id, outcome="empty_response", detail="")
            logger.warning(
                "Falling back to keyword-based generation due to empty Gemini response"
            )
            return self._generate_fallback_cards(prompt)

        except json.JSONDecodeError as e:
            logger.error("Failed to parse Gemini JSON response: %s", e)
            log_generate_cards_end(run_id=run_id, outcome="exception_json", detail=str(e))
            logger.warning(
                "Falling back to keyword-based generation due to JSON parsing failure"
            )
            return self._generate_fallback_cards(prompt)
        except Exception as e:
            logger.error("Gemini API error: %s", e)
            log_generate_cards_end(run_id=run_id, outcome="exception_api", detail=str(e))
            logger.warning(
                "Falling back to keyword-based generation due to Gemini API error"
            )
            return self._generate_fallback_cards(prompt)
    
    def _generate_fallback_cards(self, prompt: str) -> List[Dict[str, Any]]:
        """Generate cards using fallback logic based on keywords"""
        keywords = prompt.lower()
        cards = []
        matched_categories = []
        
        if any(word in keywords for word in ['web', 'app', 'website', 'application', 'mobile', 'frontend', 'backend']):
            matched_categories.append("web_app")
            cards.extend([
                {
                    "title": "Set up project repository",
                    "description": "Initialize version control system with Git, set up project structure with appropriate folders (src, docs, tests), create README.md with project overview, and configure .gitignore for the chosen technology stack.",
                    "status": "planned",
                    "order": len(cards) + 1,
                    "tags": ["setup", "git", "foundation"]
                },
                {
                    "title": "Design system architecture",
                    "description": "Create comprehensive system design including database schema, API endpoints, user flow diagrams, technology stack selection, and security considerations. Document architectural decisions and create wireframes for key user interfaces.",
                    "status": "research",
                    "order": len(cards) + 2,
                    "tags": ["architecture", "planning", "design"]
                },
                {
                    "title": "Develop user interface",
                    "description": "Build responsive frontend components using modern frameworks, implement user authentication flows, create interactive dashboards, and ensure cross-browser compatibility. Include accessibility features and mobile-responsive design.",
                    "status": "planned",
                    "order": len(cards) + 3,
                    "tags": ["frontend", "ui", "development"]
                },
                {
                    "title": "Build backend services",
                    "description": "Develop RESTful API endpoints, implement database models and migrations, set up authentication and authorization systems, create data validation layers, and implement error handling and logging mechanisms.",
                    "status": "planned",
                    "order": len(cards) + 4,
                    "tags": ["backend", "api", "development"]
                },
                {
                    "title": "Testing and deployment",
                    "description": "Write comprehensive unit and integration tests, set up continuous integration pipeline, configure production environment, implement monitoring and alerting systems, and create deployment documentation.",
                    "status": "planned",
                    "order": len(cards) + 5,
                    "tags": ["testing", "deployment", "devops"]
                }
            ])
        
        if any(word in keywords for word in ['marketing', 'campaign', 'promotion', 'social', 'brand']):
            matched_categories.append("marketing")
            cards.extend([
                {
                    "title": "Research target audience",
                    "description": "Conduct comprehensive market research to identify primary and secondary target demographics, create detailed user personas with pain points and motivations, analyze competitor strategies, and define unique value propositions.",
                    "status": "research",
                    "order": len(cards) + 1,
                    "tags": ["research", "audience", "strategy"]
                },
                {
                    "title": "Develop content strategy",
                    "description": "Create a comprehensive content calendar spanning 3 months, design brand guidelines and visual identity, plan social media campaigns across multiple platforms, and establish key performance indicators for success measurement.",
                    "status": "planned",
                    "order": len(cards) + 2,
                    "tags": ["content", "planning", "branding"]
                },
                {
                    "title": "Launch marketing campaigns",
                    "description": "Execute multi-channel marketing campaigns including social media advertising, email marketing sequences, content marketing initiatives, and partnership collaborations. Monitor performance metrics and optimize campaigns based on data.",
                    "status": "planned",
                    "order": len(cards) + 3,
                    "tags": ["execution", "campaigns", "optimization"]
                }
            ])
        
        # Add specific context-based tasks if we don't have enough
        generic_tasks = [
            {
                "title": "Project planning and requirements",
                "description": f"Define detailed project scope, gather stakeholder requirements, create timeline and milestones for: {prompt}. Establish success criteria and risk assessment.",
                "status": "research",
                "order": len(cards) + 1,
                "tags": ["planning", "requirements", "strategy"]
            },
            {
                "title": "Research and analysis",
                "description": f"Conduct thorough research on best practices, industry standards, and innovative solutions relevant to: {prompt}. Analyze market trends and competitive landscape.",
                "status": "research", 
                "order": len(cards) + 2,
                "tags": ["research", "analysis", "discovery"]
            },
            {
                "title": "Design and prototyping",
                "description": f"Create initial designs, wireframes, and prototypes for key components of: {prompt}. Focus on user experience and technical feasibility.",
                "status": "planned",
                "order": len(cards) + 3,
                "tags": ["design", "prototyping", "ux"]
            },
            {
                "title": "Implementation and development",
                "description": f"Execute the main development work for: {prompt}. Build core functionality, integrate necessary services, and ensure code quality standards.",
                "status": "planned",
                "order": len(cards) + 4,
                "tags": ["development", "implementation", "coding"]
            },
            {
                "title": "Testing and refinement",
                "description": f"Thoroughly test all aspects of: {prompt}. Perform quality assurance, gather feedback, iterate on improvements, and prepare for deployment.",
                "status": "planned",
                "order": len(cards) + 5,
                "tags": ["testing", "qa", "optimization"]
            }
        ]
        
        # Add only the cards we need to reach 5 total
        needed_cards = max(0, 5 - len(cards))
        cards.extend(generic_tasks[:needed_cards])
        logger.info(
            "Fallback generation produced %d cards (matched_categories=%s, generic_added=%d)",
            len(cards),
            matched_categories if matched_categories else ["none"],
            needed_cards
        )
        
        return cards
    
    def _format_cards(self, cards_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format cards data to ensure required fields"""
        formatted_cards = []
        
        for i, card in enumerate(cards_data, 1):
            formatted_card = {
                "title": card.get("title", f"Task {i}"),
                "description": card.get("description", ""),
                "status": card.get("status", "planned"),
                "order": card.get("order", i),
                "tags": card.get("tags", [])
            }
            
            # Validate status
            valid_statuses = ["research", "in-progress", "done", "blocked", "planned"]
            if formatted_card["status"] not in valid_statuses:
                formatted_card["status"] = "planned"
            
            # Ensure tags is a list
            if not isinstance(formatted_card["tags"], list):
                formatted_card["tags"] = []
            
            formatted_cards.append(formatted_card)
        
        return formatted_cards