# pdf_generator_api/src/schemas/form_data.py

from pydantic import BaseModel, Field, HttpUrl, RootModel
from typing import List, Dict, Any, Optional

# Modelos para form_design -> props -> styleConfig -> headerTable -> cells
class HeaderTableCell(BaseModel):
    bold: Optional[bool] = False
    align: Optional[str] = "left"
    italic: Optional[bool] = False
    colSpan: Optional[int] = 1
    content: Optional[str] = None
    rowSpan: Optional[int] = 1
    fontSize: Optional[str] = None
    textColor: Optional[str] = None
    borderColor: Optional[str] = None
    borderWidth: Optional[str] = None
    customClass: Optional[str] = None
    backgroundColor: Optional[str] = None

class HeaderTable(BaseModel):
    enabled: Optional[bool] = False
    cells: Optional[List[List[HeaderTableCell]]] = None
    width: Optional[str] = None
    borderCollapse: Optional[bool] = False
    borderWidth: Optional[str] = None
    borderColor: Optional[str] = None

class StyleConfigFont(BaseModel):
    family: Optional[str] = None
    size: Optional[str] = None
    color: Optional[str] = None

class StyleConfigFooter(BaseModel):
    text: Optional[str] = None
    show: Optional[bool] = False
    align: Optional[str] = None

class StyleConfigLogo(BaseModel):
    url: Optional[HttpUrl] = None # Usamos HttpUrl para validación de URL

class StyleConfig(BaseModel):
    backgroundColor: Optional[str] = None
    font: Optional[StyleConfigFont] = None
    borderRadius: Optional[str] = None
    borderColor: Optional[str] = None
    borderWidth: Optional[str] = None
    footer: Optional[StyleConfigFooter] = None
    headerTable: Optional[HeaderTable] = None
    logo: Optional[StyleConfigLogo] = None

# Modelos para form_design -> props
class FormDesignProps(BaseModel):
    label: Optional[str] = None
    placeholder: Optional[str] = None
    required: Optional[bool] = False
    styleConfig: Optional[StyleConfig] = None # Anidamos StyleConfig
    # Para el tipo 'location', 'label' y 'required' son las únicas propiedades,
    # así que FormDesignProps es suficientemente flexible.

# Modelos para form_design
class FormDesignItem(BaseModel):
    id: Optional[str] = None
    type: Optional[str] = None
    props: Optional[FormDesignProps] = None
    linkExternalId: Optional[int] = None
    # Las propiedades de styleConfig pueden aparecer directamente en FormDesignItem
    # según el JSON, así que las incluimos como Optional para flexibilidad.
    backgroundColor: Optional[str] = None
    font: Optional[StyleConfigFont] = None
    borderRadius: Optional[str] = None
    borderColor: Optional[str] = None
    borderWidth: Optional[str] = None
    footer: Optional[StyleConfigFooter] = None
    headerTable: Optional[HeaderTable] = None
    logo: Optional[StyleConfigLogo] = None

# Modelos para form
class Form(BaseModel):
    form_id: int
    title: str
    description: Optional[str] = None
    format_type: Optional[str] = None
    form_design: Optional[List[FormDesignItem]] = None # Anidamos FormDesignItem

# Modelos para answers
class Answer(BaseModel):
    id_answer: int
    repeated_id: Optional[int] = None
    question_id: int
    question_text: str
    question_type: str
    answer_text: Any # Puede ser string para texto o coordenadas
    file_path: Optional[str] = None

# Modelo principal para la respuesta completa del JSON
class FormData(BaseModel):
    response_id: int
    submitted_at: str
    approval_status: str
    message: Optional[str] = None
    form: Form # Anidamos Form
    answers: List[Answer] # Lista de Answers
    approvals: List[Any] # Lista de cualquier tipo para 'approvals'

# Modelo para la lista de respuestas (el JSON raíz es una lista de objetos FormData)
class FormResponseList(RootModel[List[FormData]]):
    pass