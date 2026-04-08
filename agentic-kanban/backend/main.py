from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import List, Optional
import uvicorn
import logging
import traceback
import sys
from datetime import datetime
from pydantic import BaseModel

from models import Card, CardList, CardUpdate, CardResponse, CardsResponse, reload_models, dynamic_models
from database import CardDatabase
from agent_service import AgentService
from workspace_store import clear_workspace, get_workspace_path, set_workspace

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('backend.log')
    ]
)
logger = logging.getLogger(__name__)


class GenerateCardsRequest(BaseModel):
    prompt: str


class WorkspaceSetRequest(BaseModel):
    """Absolute path on the machine running the backend. Empty clears the workspace."""

    path: Optional[str] = None

# Initialize FastAPI app
app = FastAPI(
    title="Agentic Kanban Backend",
    description="Backend API for managing kanban board cards",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database
try:
    db = CardDatabase()
    logger.info("Database initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize database: {e}")
    logger.error(traceback.format_exc())
    db = None

# Initialize agent service
try:
    agent_service = AgentService()
    logger.info("Agent service initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize agent service: {e}")
    logger.error(traceback.format_exc())
    agent_service = None


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler to catch all unhandled errors"""
    error_msg = f"Unhandled error: {str(exc)}"
    logger.error(f"Global exception handler caught: {error_msg}")
    logger.error(f"Request: {request.method} {request.url}")
    logger.error(f"Traceback: {traceback.format_exc()}")
    
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "Internal server error",
            "error": error_msg,
            "timestamp": datetime.now().isoformat()
        }
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with logging"""
    logger.warning(f"HTTP exception: {exc.status_code} - {exc.detail}")
    logger.warning(f"Request: {request.method} {request.url}")
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.now().isoformat()
        }
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Middleware to log all requests and responses"""
    start_time = datetime.now()
    
    # Log request
    logger.info(f"Request: {request.method} {request.url}")
    if request.query_params:
        logger.info(f"Query params: {dict(request.query_params)}")
    
    try:
        response = await call_next(request)
        
        # Log response
        process_time = (datetime.now() - start_time).total_seconds()
        logger.info(f"Response: {response.status_code} - {process_time:.3f}s")
        
        return response
        
    except Exception as e:
        # Log any errors in middleware
        process_time = (datetime.now() - start_time).total_seconds()
        logger.error(f"Middleware error: {str(e)} - {process_time:.3f}s")
        logger.error(traceback.format_exc())
        raise


@app.get("/")
async def root():
    """Health check endpoint"""
    logger.info("Health check endpoint called")
    try:
        return {"message": "Agentic Kanban Backend is running!"}
    except Exception as e:
        logger.error(f"Error in health check: {e}")
        logger.error(traceback.format_exc())
        raise


@app.get("/api/schema")
async def get_schema_info():
    """Get information about the current JSON schema"""
    logger.info("Schema info endpoint called")
    try:
        if not dynamic_models:
            raise HTTPException(status_code=500, detail="Dynamic models not initialized")
        
        schema_info = dynamic_models.get_schema_info()
        logger.info(f"Schema info retrieved successfully: {len(schema_info)} properties")
        
        return {
            "success": True,
            "message": "Schema information retrieved successfully",
            "data": schema_info
        }
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Failed to get schema info: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_msg)


@app.post("/api/schema/reload")
async def reload_schema():
    """Reload the schema and regenerate models"""
    logger.info("Schema reload endpoint called")
    try:
        if not dynamic_models:
            raise HTTPException(status_code=500, detail="Dynamic models not initialized")
        
        reload_models()
        logger.info("Schema reloaded successfully")
        
        return {
            "success": True,
            "message": "Schema reloaded successfully",
            "data": {
                "message": "All models have been regenerated from the schema file"
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Failed to reload schema: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_msg)


@app.get("/api/workspace")
async def get_workspace():
    """Return the configured agent workspace directory (server-side path)."""
    logger.info("Get workspace endpoint called")
    path = get_workspace_path()
    return {
        "success": True,
        "message": "Workspace status retrieved",
        "data": {"path": path, "configured": bool(path)},
    }


@app.post("/api/workspace")
async def post_workspace(request: WorkspaceSetRequest):
    """Set or clear the directory agents may read/write via tool calls."""
    logger.info("Set workspace endpoint called")
    try:
        raw = (request.path or "").strip()
        if not raw:
            clear_workspace()
            return {
                "success": True,
                "message": "Workspace cleared",
                "data": {"path": None, "configured": False},
            }
        resolved = set_workspace(raw)
        return {
            "success": True,
            "message": "Workspace updated",
            "data": {"path": resolved, "configured": True},
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        error_msg = f"Failed to set workspace: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_msg)


@app.post("/api/generate-cards", response_model=CardResponse)
async def generate_cards_with_agent(request: GenerateCardsRequest):
    """
    Generate kanban cards using the AI agent (Gemini when configured) from a prompt.
    If a workspace is set via POST /api/workspace, the model may list, read, and write
    files only under that directory while generating tasks.

    Args:
        request: Request containing the user prompt

    Returns:
        Success response with message
    """
    logger.info(f"Generate cards endpoint called with prompt: {request.prompt[:100]}...")
    logger.debug("Agent generate request metadata: prompt_length=%d", len(request.prompt))
    try:
        if not agent_service:
            raise HTTPException(status_code=500, detail="Agent service not initialized")
        
        if not db:
            raise HTTPException(status_code=500, detail="Database not initialized")
        
        logger.debug(
            "Agent service readiness: model_configured=%s",
            bool(getattr(agent_service, "model", None) and getattr(agent_service, "gemini_api_key", None))
        )
        
        # Generate cards using the agent (optional workspace for file tools)
        workspace = get_workspace_path()
        cards_data = await agent_service.generate_cards_from_prompt(
            request.prompt, workspace_path=workspace
        )
        logger.info("Agent returned %d cards before DB insert", len(cards_data) if cards_data else 0)
        
        if not cards_data:
            raise HTTPException(status_code=500, detail="Agent failed to generate cards")
        
        # Create Card objects for the database
        cards_for_db = []
        for card_data in cards_data:
            # Create a card with all required fields
            card_dict = {
                "id": f"agent-{datetime.now().timestamp()}-{len(cards_for_db)}",
                "title": card_data.get("title", "Untitled"),
                "description": card_data.get("description", ""),
                "status": card_data.get("status", "planned"),
                "order": card_data.get("order", len(cards_for_db) + 1),
                "tags": card_data.get("tags", []),
                "createdAt": datetime.now().isoformat(),
                "updatedAt": datetime.now().isoformat(),
                "completedAt": None
            }
            cards_for_db.append(card_dict)
        
        # Create CardList object
        card_list = CardList(cards=cards_for_db)
        
        # Add cards to database
        card_ids = db.add_cards(card_list.cards)
        logger.info(f"Successfully generated and added {len(card_ids)} cards using agent")
        
        return CardResponse(
            success=True,
            message=f"Successfully generated {len(card_ids)} cards using AI agent",
            data=None
        )
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Failed to generate cards with agent: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_msg)


@app.post("/api/cards", response_model=CardResponse)
async def put_cards(card_list: CardList):
    """
    Add multiple cards to the database
    
    Args:
        card_list: List of cards to add
        
    Returns:
        Success response with message
    """
    logger.info(f"PUT cards endpoint called with {len(card_list.cards)} cards")
    logger.debug(f"Card list: {card_list}")
    try:
        if not db:
            raise HTTPException(status_code=500, detail="Database not initialized")
        
        # Add cards to database
        card_ids = db.add_cards(card_list.cards)
        logger.info(f"Successfully added {len(card_ids)} cards to database")
        
        return CardResponse(
            success=True,
            message=f"Successfully added {len(card_ids)} cards",
            data=None
        )
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Failed to add cards: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_msg)


@app.get("/api/cards", response_model=CardsResponse)
async def get_cards():
    """
    Retrieve all cards from the database
    
    Returns:
        List of all cards
    """
    logger.info("GET cards endpoint called")
    try:
        if not db:
            raise HTTPException(status_code=500, detail="Database not initialized")
        
        cards = db.get_all_cards()
        logger.info(f"Successfully retrieved {len(cards)} cards from database")
        
        return CardsResponse(
            success=True,
            message=f"Successfully retrieved {len(cards)} cards",
            data=cards
        )
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Failed to retrieve cards: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_msg)


@app.put("/api/cards/{card_id}", response_model=CardResponse)
async def update_card(card_id: str, updates: CardUpdate):
    """
    Update a specific card in the database
    
    Args:
        card_id: ID of the card to update
        updates: Fields to update
        
    Returns:
        Updated card data
    """
    logger.info(f"UPDATE card endpoint called for card_id: {card_id}")
    try:
        if not db:
            raise HTTPException(status_code=500, detail="Database not initialized")
        
        # Check if card exists
        existing_card = db.get_card_by_id(card_id)
        if not existing_card:
            error_msg = f"Card with ID {card_id} not found"
            logger.warning(error_msg)
            raise HTTPException(status_code=404, detail=error_msg)
        
        # Update the card
        updated_card = db.update_card(card_id, updates)
        if not updated_card:
            error_msg = "Failed to update card"
            logger.error(error_msg)
            raise HTTPException(status_code=500, detail=error_msg)
        
        logger.info(f"Successfully updated card {card_id}")
        return CardResponse(
            success=True,
            message="Card updated successfully",
            data=updated_card
        )
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Failed to update card: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_msg)


@app.get("/api/cards/{card_id}", response_model=CardResponse)
async def get_card(card_id: str):
    """
    Get a specific card by ID
    
    Args:
        card_id: ID of the card to retrieve
        
    Returns:
        Card data
    """
    logger.info(f"GET single card endpoint called for card_id: {card_id}")
    try:
        if not db:
            raise HTTPException(status_code=500, detail="Database not initialized")
        
        card = db.get_card_by_id(card_id)
        if not card:
            error_msg = f"Card with ID {card_id} not found"
            logger.warning(error_msg)
            raise HTTPException(status_code=404, detail=error_msg)
        
        logger.info(f"Successfully retrieved card {card_id}")
        return CardResponse(
            success=True,
            message="Card retrieved successfully",
            data=card
        )
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Failed to retrieve card: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_msg)


@app.delete("/api/cards/{card_id}")
async def delete_card(card_id: str):
    """
    Delete a specific card from the database
    
    Args:
        card_id: ID of the card to delete
        
    Returns:
        Success message
    """
    logger.info(f"DELETE card endpoint called for card_id: {card_id}")
    try:
        if not db:
            raise HTTPException(status_code=500, detail="Database not initialized")
        
        # Check if card exists
        existing_card = db.get_card_by_id(card_id)
        if not existing_card:
            error_msg = f"Card with ID {card_id} not found"
            logger.warning(error_msg)
            raise HTTPException(status_code=404, detail=error_msg)
        
        # Delete the card
        success = db.delete_card(card_id)
        if not success:
            error_msg = "Failed to delete card"
            logger.error(error_msg)
            raise HTTPException(status_code=500, detail=error_msg)
        
        logger.info(f"Successfully deleted card {card_id}")
        return {"message": "Card deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Failed to delete card: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_msg)


@app.delete("/api/cards")
async def delete_all_cards():
    """
    Delete all cards from the database
    
    Returns:
        Success message with count of deleted cards
    """
    logger.info("DELETE all cards endpoint called")
    try:
        if not db:
            raise HTTPException(status_code=500, detail="Database not initialized")
        
        # Get current card count before deletion
        cards = db.get_all_cards()
        card_count = len(cards)
        
        # Delete all cards
        success = db.delete_all_cards()
        if not success:
            error_msg = "Failed to delete all cards"
            logger.error(error_msg)
            raise HTTPException(status_code=500, detail=error_msg)
        
        logger.info(f"Successfully deleted all {card_count} cards")
        return {"message": f"Successfully deleted all {card_count} cards"}
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Failed to delete all cards: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_msg)


@app.get("/api/tracks")
async def get_implemented_tracks():
    """
    Get information about implemented hackathon tracks and their impact on functionality
    
    Returns:
        Detailed information about which tracks are implemented and how they enhance the system
    """
    logger.info("GET tracks endpoint called")
    try:
        import os
        import subprocess
        from pathlib import Path
        
        # Get git branch info
        try:
            result = subprocess.run(['git', 'branch'], capture_output=True, text=True, cwd='.')
            branches = result.stdout.strip().split('\n')
            current_branch = None
            track_branches = []
            for branch in branches:
                branch = branch.strip()
                if branch.startswith('* '):
                    current_branch = branch[2:]
                if 'track' in branch.lower():
                    track_branches.append(branch.replace('* ', ''))
        except:
            current_branch = "unknown"
            track_branches = []
        
        # Check for MCP server
        mcp_exists = os.path.exists("../mcp/fastmcp_server.py")
        
        # Check for agent service
        agent_service_exists = os.path.exists("agent_service.py")
        
        # Analyze implemented tracks
        implemented_tracks = {
            "track-14": {
                "name": "Local MCP Standard Agent",
                "status": "implemented",
                "description": "Model Context Protocol server integration for AI agent communication",
                "implementation": {
                    "mcp_server": "../mcp/fastmcp_server.py",
                    "agent_service": "agent_service.py",
                    "tools_provided": [
                        "create_kanban_cards",
                        "get_all_kanban_cards", 
                        "search_kanban_cards",
                        "update_kanban_card",
                        "get_kanban_schema",
                        "get_kanban_stats"
                    ]
                },
                "functionality_impact": [
                    "Enables AI agents to create and manage kanban cards programmatically",
                    "Provides standardized MCP protocol for agent-to-backend communication",
                    "Supports complex card operations like search, update, and statistics",
                    "Allows external AI systems to interact with the kanban board"
                ],
                "evidence": mcp_exists
            },
            "track-15": {
                "name": "Agent Behavior Modification (Kanban Board)",
                "status": "implemented", 
                "description": "Intelligent kanban board with AI-powered task generation and management",
                "implementation": {
                    "backend_api": "FastAPI backend with ChromaDB storage",
                    "frontend": "Next.js React application with drag-and-drop kanban interface",
                    "ai_integration": "Google Gemini AI for task generation with fallback logic",
                    "features": [
                        "AI-powered task generation from natural language prompts",
                        "Interactive drag-and-drop kanban board",
                        "Task detail dialogs with comprehensive information",
                        "Real-time card management and status updates",
                        "Tag-based organization and filtering"
                    ]
                },
                "functionality_impact": [
                    "Transforms simple prompts into structured, actionable tasks",
                    "Provides context-aware task generation (web/app vs marketing projects)",
                    "Enables visual project management with intuitive drag-and-drop interface",
                    "Supports collaborative workflow with detailed task tracking",
                    "Integrates AI assistance directly into project planning workflow"
                ],
                "evidence": current_branch == "track-15-kanban-board"
            },
            "track-05": {
                "name": "OpenAPI Minifier",
                "status": "partial",
                "description": "4-phase OpenAPI specification minification system",
                "implementation": {
                    "location": "../tracks/track-05-openapi-minifier/",
                    "components": [
                        "spec_minifier.py - Core minification engine",
                        "parser.py - OpenAPI specification parser", 
                        "analyzer.py - Dependency analysis",
                        "extractor.py - Schema extraction",
                        "validator.py - Specification validation"
                    ]
                },
                "functionality_impact": [
                    "Would enable reduction of OpenAPI spec size for agent consumption",
                    "Could optimize API specifications for LLM context limits", 
                    "Would support selective API feature extraction",
                    "Could enhance agent's ability to work with large API specifications"
                ],
                "evidence": os.path.exists("../tracks/track-05-openapi-minifier/spec_minifier.py")
            }
        }
        
        # Count active implementations
        active_tracks = sum(1 for track in implemented_tracks.values() if track["evidence"])
        
        # Overall system architecture impact
        system_architecture = {
            "agent_integration": {
                "description": "Multi-layered agent communication system",
                "components": [
                    "FastMCP Server - Standardized agent protocol interface",
                    "Agent Service - AI-powered task generation with Gemini integration", 
                    "Fallback Logic - Keyword-based task generation when AI unavailable",
                    "ChromaDB Storage - Vector database for persistent task storage"
                ]
            },
            "user_experience": {
                "description": "Modern, interactive kanban board application",
                "features": [
                    "Natural language task generation",
                    "Drag-and-drop task management",
                    "Real-time status updates",
                    "Detailed task dialogs",
                    "Responsive design with dark mode support"
                ]
            },
            "scalability": {
                "description": "Designed for extensibility and future track integration",
                "aspects": [
                    "Modular backend API supporting additional track implementations",
                    "MCP protocol enables easy agent integration",
                    "ChromaDB provides vector similarity search capabilities",
                    "React frontend supports component-based feature additions"
                ]
            }
        }
        
        return {
            "success": True,
            "message": "Successfully retrieved track implementation information",
            "data": {
                "summary": {
                    "total_tracks_available": 20,
                    "implemented_tracks": active_tracks,
                    "current_branch": current_branch,
                    "primary_focus": "Agent-powered kanban board with MCP integration"
                },
                "implemented_tracks": implemented_tracks,
                "system_architecture": system_architecture,
                "integration_benefits": [
                    "Seamless AI-human collaboration in project management",
                    "Standardized agent communication through MCP protocol",
                    "Extensible architecture supporting future hackathon tracks",
                    "Real-time interactive interface with persistent storage",
                    "Context-aware task generation adapting to project type"
                ]
            }
        }
        
    except Exception as e:
        error_msg = f"Failed to retrieve track information: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_msg)


if __name__ == "__main__":
    logger.info("Starting Agentic Kanban Backend...")
    try:
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            log_level="info"
        )
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)
