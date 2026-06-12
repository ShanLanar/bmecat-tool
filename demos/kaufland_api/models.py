"""
Datenmodelle für Kaufland-Daten
"""

from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Any
from datetime import datetime


@dataclass
class Price:
    """Preismodell"""
    amount: float
    currency: str = "EUR"
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Inventory:
    """Bestandsmodell"""
    quantity: int
    sku: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class Category:
    """Kategoriemodell"""
    id: int
    name: str
    parent_id: Optional[int] = None
    attributes: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "parent_id": self.parent_id,
            "attributes": self.attributes
        }


@dataclass
class Attribute:
    """Attributmodell"""
    id: int
    name: str
    type: str  # text, number, select, etc.
    values: List[str] = field(default_factory=list)
    required: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "values": self.values,
            "required": self.required
        }


@dataclass
class Product:
    """Produktmodell - Kerndatenstruktur"""
    id: int
    sku: str
    title: str
    description: Optional[str] = None
    price: Optional[Price] = None
    inventory: Optional[Inventory] = None
    category_id: Optional[int] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    images: List[str] = field(default_factory=list)
    
    # Erweiterungen für zukünftige Felder
    image_names: Optional[Dict[str, str]] = None  # {image_url: name}
    gpsr_data: Optional[Dict[str, Any]] = None    # GPSR-Informationen
    
    status: str = "active"  # active, inactive, draft
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def to_dict(self, exclude_none: bool = False) -> Dict[str, Any]:
        """
        Konvertiere zu Dictionary
        
        Args:
            exclude_none: Entferne None-Werte
            
        Returns:
            Dictionary-Darstellung
        """
        result = {
            "id": self.id,
            "sku": self.sku,
            "title": self.title,
            "description": self.description,
            "price": self.price.to_dict() if self.price else None,
            "inventory": self.inventory.to_dict() if self.inventory else None,
            "category_id": self.category_id,
            "attributes": self.attributes,
            "images": self.images,
            "image_names": self.image_names,
            "gpsr_data": self.gpsr_data,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
        
        if exclude_none:
            return {k: v for k, v in result.items() if v is not None}
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Product":
        """Erstelle Produkt aus Dictionary"""
        try:
            return cls(
                id=data.get("id", 0),
                sku=data.get("sku", ""),
                title=data.get("title", ""),
                description=data.get("description"),
                price=Price(**data["price"]) if data.get("price") else None,
                inventory=Inventory(**data["inventory"]) if data.get("inventory") else None,
                category_id=data.get("category_id"),
                attributes=data.get("attributes", {}),
                images=data.get("images", []),
                image_names=data.get("image_names"),
                gpsr_data=data.get("gpsr_data"),
                status=data.get("status", "active"),
                created_at=cls._parse_datetime(data.get("created_at")),
                updated_at=cls._parse_datetime(data.get("updated_at"))
            )
        except KeyError as e:
            raise ValueError(f"Erforderliches Feld fehlt: {e}")
    
    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        """Parse ISO-Format Datetime"""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None


@dataclass
class ProductBatch:
    """Batch von Produkten für Bulk-Operationen"""
    products: List[Product]
    operation: str  # create, update, delete
    
    def to_list_of_dicts(self) -> List[Dict[str, Any]]:
        """Konvertiere zu Liste von Dictionaries"""
        return [p.to_dict() for p in self.products]
    
    @property
    def count(self) -> int:
        """Anzahl der Produkte"""
        return len(self.products)
