import ast
import chromadb
import json
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
import logging
import traceback
from models import Card, CardUpdate, dynamic_models

# Get logger for this module
logger = logging.getLogger(__name__)

# Chroma metadata is string-only; we must not write Python None as the literal "None" for
# optional fields that are parsed back as datetimes or enums (see all_card_dict_fields_to_str).
_METADATA_SKIP_NONE_KEYS = frozenset(
    {"completedAt", "lastAgentRunAt", "lastAgentSummary", "agentStatus"}
)


def _parse_metadata_datetime(value: Any) -> Optional[datetime]:
    """Parse a Chroma metadata value into datetime, or None if absent / placeholder."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s == "None":
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Invalid datetime in card metadata: %r", value)
        return None


def _normalize_optional_metadata_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s == "None":
        return None
    return s


def _parse_metadata_tags(value: Any) -> List[str]:
    """Chroma stores tags as a string; merged updates may still have tags as a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(t) for t in value if t is not None]
    s = str(value).strip()
    if not s or s == "None":
        return []
    try:
        parsed = ast.literal_eval(s)
    except (ValueError, SyntaxError):
        logger.warning("Could not parse tags metadata: %r", value)
        return []
    if isinstance(parsed, (list, tuple)):
        return [str(t) for t in parsed if t is not None]
    return [str(parsed)]


def _updates_to_plain_dict(updates: Any) -> Dict[str, Any]:
    """Pydantic v1/v2 compatible dump for merge into Chroma metadata."""
    if hasattr(updates, "model_dump"):
        return updates.model_dump(exclude_unset=True, mode="python")
    return updates.dict(exclude_unset=True)


class CardDatabase:
    def __init__(self, persist_directory: str = "./chroma_db"):
        """Initialize ChromaDB client and collection for cards"""
        try:
            logger.info(f"Initializing ChromaDB with persist directory: {persist_directory}")
            self.client = chromadb.PersistentClient(path=persist_directory)
            
            # Create or get the cards collection
            try:
                logger.info("Attempting to get existing cards collection...")
                self.collection = self.client.get_collection("cards")
                logger.info("Successfully connected to existing cards collection")
            except Exception as e:
                logger.info(f"Collection not found, creating new one: {e}")
                self.collection = self.client.create_collection(
                    name="cards",
                    metadata={"description": "Kanban board cards storage"}
                )
                logger.info("Successfully created new cards collection")
                
        except Exception as e:
            error_msg = f"Failed to initialize ChromaDB: {e}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            raise RuntimeError(error_msg)
    
    def add_cards(self, cards: List[Card]) -> List[str]:
        """Add multiple cards to the database"""
        logger.info(f"Adding {len(cards)} cards to database")
        
        try:
            card_ids = []
            documents = []
            metadatas = []
            
            for i, card in enumerate(cards):
                try:
                    # Generate ID if not provided
                    if not hasattr(card, 'id') or not card.id:
                        card.id = str(uuid.uuid4())
                        logger.debug(f"Generated new ID for card {i}: {card.id}")
                    
                    # Update timestamps
                    now = datetime.utcnow()
                    if not hasattr(card, 'createdAt') or not card.createdAt:
                        card.createdAt = now
                        logger.debug(f"Set createdAt for card {i}: {now}")
                    if hasattr(card, 'updatedAt'):
                        card.updatedAt = now
                        logger.debug(f"Set updatedAt for card {i}: {now}")
                    if hasattr(card, 'tags'):
                        card.tags = str([tag.lower() for tag in card.tags])
                    
                    # Convert card to document format
                    card_dict = card.dict()
                    logger.debug(f"Card dict: {card_dict}")
                    
                    # Handle datetime fields
                    if hasattr(card, 'createdAt') and card.createdAt:
                        card_dict['createdAt'] = card.createdAt.isoformat()
                    if hasattr(card, 'updatedAt') and card.updatedAt:
                        card_dict['updatedAt'] = card.updatedAt.isoformat()
                    if hasattr(card, 'completedAt') and card.completedAt:
                        card_dict['completedAt'] = card.completedAt.isoformat()
                    
                    documents.append(json.dumps(card_dict))
                    metadatas.append(card_dict)
                    card_ids.append(card.id)
                    
                    logger.debug(f"Prepared card {i} with ID: {card.id}")
                    
                except Exception as e:
                    error_msg = f"Failed to prepare card {i}: {e}"
                    logger.error(error_msg)
                    logger.error(traceback.format_exc())
                    raise RuntimeError(error_msg)
            
            # Add to ChromaDB
            logger.info(f"Adding {len(card_ids)} cards to ChromaDB collection")
            processed_metadatas = [all_card_dict_fields_to_str(metadata) for metadata in metadatas]
            logger.debug(f"Processed metadatas: {processed_metadatas}")
            self.collection.add(
                documents=documents,
                metadatas=processed_metadatas,
                ids=card_ids
            )
            
            logger.info(f"Successfully added {len(card_ids)} cards to database")
            return card_ids
            
        except Exception as e:
            error_msg = f"Failed to add cards to database: {e}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            raise RuntimeError(error_msg)
    
    def get_all_cards(self) -> List[Card]:
        """Retrieve all cards from the database"""
        logger.info("Retrieving all cards from database")
        
        try:
            results = self.collection.get()
            logger.debug(f"Retrieved {len(results.get('metadatas', []))} cards from ChromaDB")
            
            cards = []
            
            for i, metadata in enumerate(results['metadatas']):
                if metadata:
                    try:
                        # Convert metadata back to Card object
                        card_data = metadata.copy()
                        
                        # Parse datetime fields if they exist
                        if 'createdAt' in card_data:
                            card_data['createdAt'] = datetime.fromisoformat(metadata['createdAt'])
                        if 'updatedAt' in card_data:
                            card_data['updatedAt'] = datetime.fromisoformat(metadata['updatedAt'])
                        # Handle completedAt field - it might be missing, "None", or a valid datetime
                        if 'completedAt' in metadata and metadata.get('completedAt'):
                            # Handle legacy "None" strings and new null values
                            if metadata['completedAt'] != "None" and metadata['completedAt'] is not None:
                                card_data['completedAt'] = datetime.fromisoformat(metadata['completedAt'])
                            else:
                                card_data['completedAt'] = None
                        else:
                            # completedAt field is missing or empty - set to None
                            card_data['completedAt'] = None
                        if 'tags' in card_data:
                            card_data['tags'] = _parse_metadata_tags(metadata['tags'])
                        card_data["lastAgentRunAt"] = _parse_metadata_datetime(
                            metadata.get("lastAgentRunAt")
                        )
                        if "lastAgentSummary" in metadata:
                            card_data["lastAgentSummary"] = _normalize_optional_metadata_str(
                                metadata.get("lastAgentSummary")
                            )
                        if "agentStatus" in metadata:
                            card_data["agentStatus"] = _normalize_optional_metadata_str(
                                metadata.get("agentStatus")
                            )

                        # Create Card object using current model
                        card = Card(**card_data)
                        cards.append(card)
                        logger.debug(f"Successfully created card {i} with ID: {card_data.get('id', 'unknown')}")
                        
                    except Exception as e:
                        logger.warning(f"Could not create card from data {i}: {e}")
                        logger.debug(f"Problematic card data: {metadata}")
                        # Skip invalid cards
                        continue
            
            # Sort by order if order field exists
            if cards and hasattr(cards[0], 'order'):
                cards.sort(key=lambda x: getattr(x, 'order', 0))
                logger.debug("Sorted cards by order field")
            
            logger.info(f"Successfully retrieved {len(cards)} valid cards from database")
            return cards
            
        except Exception as e:
            error_msg = f"Failed to retrieve cards from database: {e}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            raise RuntimeError(error_msg)
    
    def update_card(self, card_id: str, updates: CardUpdate) -> Optional[Card]:
        """Update a specific card in the database"""
        logger.info(f"Updating card {card_id} in database")
        
        try:
            # Get current card
            results = self.collection.get(ids=[card_id])
            if not results["metadatas"]:
                logger.warning("Card %s not found for update (Chroma returned no metadata)", card_id)
                return None
            
            current_metadata = results['metadatas'][0]
            logger.debug(f"Current card data: {current_metadata}")
            
            # Update fields
            update_dict = _updates_to_plain_dict(updates)
            if update_dict:
                logger.debug(f"Update fields: {update_dict}")
                
                # Update timestamp if updatedAt field exists
                if 'updatedAt' in current_metadata:
                    update_dict['updatedAt'] = datetime.utcnow().isoformat()
                    logger.debug("Added updatedAt timestamp to update")
                
                # Merge updates with current data
                updated_metadata = current_metadata.copy()
                updated_metadata.update(update_dict)
                
                # Update the document
                updated_document = str(updated_metadata)
                
                # Update in ChromaDB
                logger.info(f"Updating card {card_id} in ChromaDB")
                self.collection.update(
                    ids=[card_id],
                    documents=[updated_document],
                    metadatas=[all_card_dict_fields_to_str(updated_metadata)]
                )
                
                # Return updated card
                card_data = updated_metadata.copy()
                
                # Parse datetime fields
                if 'createdAt' in card_data:
                    card_data['createdAt'] = updated_metadata['createdAt']
                if 'updatedAt' in card_data:
                    card_data['updatedAt'] = updated_metadata['updatedAt']
                if 'completedAt' in card_data and updated_metadata.get('completedAt'):
                    if updated_metadata['completedAt'] != "None":
                        card_data['completedAt'] = updated_metadata['completedAt']
                    else:
                        card_data['completedAt'] = None
                if 'tags' in card_data:
                    card_data['tags'] = _parse_metadata_tags(updated_metadata['tags'])
                card_data["lastAgentRunAt"] = _parse_metadata_datetime(
                    updated_metadata.get("lastAgentRunAt")
                )
                if "lastAgentSummary" in updated_metadata:
                    card_data["lastAgentSummary"] = _normalize_optional_metadata_str(
                        updated_metadata.get("lastAgentSummary")
                    )
                if "agentStatus" in updated_metadata:
                    card_data["agentStatus"] = _normalize_optional_metadata_str(
                        updated_metadata.get("agentStatus")
                    )

                updated_card = Card(**card_data)
                logger.info(f"Successfully updated card {card_id}")
                return updated_card
            else:
                logger.info(
                    "No updates provided for card %s (empty model dump — check Pydantic field names)",
                    card_id,
                )
                return None
            
        except Exception as e:
            error_msg = f"Failed to update card {card_id}: {e}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            raise RuntimeError(error_msg)
    
    def delete_card(self, card_id: str) -> bool:
        """Delete a card from the database"""
        logger.info(f"Deleting card {card_id} from database")
        
        try:
            self.collection.delete(ids=[card_id])
            logger.info(f"Successfully deleted card {card_id} from database")
            return True
            
        except Exception as e:
            error_msg = f"Failed to delete card {card_id}: {e}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            raise RuntimeError(error_msg)
    
    def get_card_by_id(self, card_id: str) -> Optional[Card]:
        """Get a specific card by ID"""
        logger.debug(f"Retrieving card {card_id} from database")
        
        try:
            results = self.collection.get(ids=[card_id])
            if not results['metadatas']:
                logger.debug(f"Card {card_id} not found in database")
                return None
            
            metadata = results['metadatas'][0]
            card_data = metadata.copy()
            
            # Parse datetime fields if they exist
            if 'createdAt' in card_data:
                card_data['createdAt'] = datetime.fromisoformat(metadata['createdAt'])
            if 'updatedAt' in card_data:
                card_data['updatedAt'] = datetime.fromisoformat(metadata['updatedAt'])
            # Handle completedAt field - it might be missing, "None", or a valid datetime
            if 'completedAt' in metadata and metadata.get('completedAt'):
                # Handle legacy "None" strings and new null values
                if metadata['completedAt'] != "None" and metadata['completedAt'] is not None:
                    card_data['completedAt'] = datetime.fromisoformat(metadata['completedAt'])
                else:
                    card_data['completedAt'] = None
            else:
                # completedAt field is missing or empty - set to None
                card_data['completedAt'] = None
            if 'tags' in card_data:
                card_data['tags'] = _parse_metadata_tags(metadata['tags'])
            card_data["lastAgentRunAt"] = _parse_metadata_datetime(
                metadata.get("lastAgentRunAt")
            )
            if "lastAgentSummary" in metadata:
                card_data["lastAgentSummary"] = _normalize_optional_metadata_str(
                    metadata.get("lastAgentSummary")
                )
            if "agentStatus" in metadata:
                card_data["agentStatus"] = _normalize_optional_metadata_str(
                    metadata.get("agentStatus")
                )

            card = Card(**card_data)
            logger.debug(f"Successfully retrieved card {card_id}")
            return card
            
        except Exception as e:
            error_msg = f"Failed to retrieve card {card_id}: {e}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            raise RuntimeError(error_msg)
    
    def reload_schema(self):
        """Reload the schema and regenerate models"""
        logger.info("Reloading schema in database module")
        try:
            if dynamic_models:
                dynamic_models.reload_models()
                logger.info("Schema reloaded successfully in database module")
                return True
            else:
                logger.warning("Dynamic models not available for schema reload")
                return False
                
        except Exception as e:
            error_msg = f"Failed to reload schema in database module: {e}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            return False
    
    def delete_all_cards(self) -> bool:
        """Delete all cards from the database"""
        logger.info("Deleting all cards from database")
        
        try:
            # Get all card IDs
            results = self.collection.get()
            card_ids = results.get('ids', [])
            
            if not card_ids:
                logger.info("No cards to delete")
                return True
            
            # Delete all cards
            self.collection.delete(ids=card_ids)
            logger.info(f"Successfully deleted {len(card_ids)} cards from database")
            return True
            
        except Exception as e:
            error_msg = f"Failed to delete all cards: {e}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            raise RuntimeError(error_msg)
    
    def get_database_info(self) -> Dict[str, Any]:
        """Get information about the database"""
        try:
            collection_count = len(self.collection.get()['ids']) if self.collection else 0
            
            return {
                "database_type": "ChromaDB",
                "collection_name": "cards",
                "total_cards": collection_count,
                "persist_directory": getattr(self.client, '_persist_directory', 'unknown'),
                "status": "connected" if self.collection else "disconnected"
            }
            
        except Exception as e:
            logger.error(f"Failed to get database info: {e}")
            return {
                "database_type": "ChromaDB",
                "status": "error",
                "error": str(e)
            }


def all_card_dict_fields_to_str(card_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Convert all fields of a card dict to strings"""
    result = {}
    for key, value in card_dict.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, list):
            result[key] = str([str(item) for item in value])
        elif value is None:
            # ChromaDB doesn't accept None in metadata; skip optional fields instead of
            # storing the literal string "None" (breaks datetime/enum parsing on read).
            if key not in _METADATA_SKIP_NONE_KEYS:
                result[key] = "None"
        else:
            result[key] = str(value)
    return result
