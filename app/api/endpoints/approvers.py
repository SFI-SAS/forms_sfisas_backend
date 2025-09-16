from typing import List, Optional
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import and_, func
from sqlalchemy.orm import Session
from app.crud import get_forms_by_approver, save_form_approvals, update_response_approval_status
from app.database import get_db
from app.core.security import get_current_user
import pandas as pd
from app.models import ApprovalRequirement, ApprovalStatus, Form, FormApproval, Response, ResponseApproval, ResponseApprovalRequirement, User
from app.schemas import ApprovalRequirementsCreateSchema, BulkUpdateFormApprovals, FormApprovalCreateSchema, FormWithApproversResponse, UpdateResponseApprovalRequest

router = APIRouter()

class ResponseApprovalRequirementCreateItem(BaseModel):
    response_id: int
    approval_requirement_id: int
    fulfilling_response_id: Optional[int] = None
    is_fulfilled: bool = False

class ResponseApprovalRequirementsCreateSchema(BaseModel):
    requirements: List[ResponseApprovalRequirementCreateItem]

@router.post("/form-approvals/create")
def create_form_approvals(
    data: FormApprovalCreateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Crea aprobaciones para un formulario específico.
    
    - Requiere que el usuario actual esté autenticado.
    - Valida la existencia del formulario.
    - Agrega aprobadores si no existen o si el número de secuencia es diferente.
    - Permite configurar formularios requeridos y secuencia de aprobación.
    
    Args:
        data (FormApprovalCreateSchema): Datos del formulario y aprobadores.
            - form_id: ID del formulario principal
            - approvers: Lista de aprobadores con:
                - user_id: ID del usuario aprobador
                - sequence_number: Orden en la secuencia de aprobación
                - is_mandatory: Si la aprobación es obligatoria
                - deadline_days: Días límite para aprobar
                - is_active: Si el aprobador está activo
        db (Session): Sesión de la base de datos inyectada por dependencia.
        current_user (User): Usuario autenticado actual.
    
    Returns:
        dict: Diccionario con los IDs de los nuevos aprobadores agregados y resumen de configuración.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission"
        )
    
    try:
        new_ids = save_form_approvals(data, db)
        
        # Información adicional sobre la configuración creada
        total_approvers = len(data.approvers)
        
        return {
            "success": True,
            "message": "Aprobaciones creadas exitosamente",
            "new_user_ids": new_ids,
            "summary": {
                "total_approvers_configured": total_approvers,
                "new_approvers_added": len(new_ids),
                "form_id": data.form_id
            }
        }
    
    except HTTPException as e:
        # Re-raise HTTP exceptions (como formulario no encontrado)
        raise e
    except Exception as e:
        # Manejo de errores inesperados
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )
        


@router.put("/update-response-approval/{response_id}")
async def update_response_approval(
    request: Request,
    response_id: int,
    update_data: UpdateResponseApprovalRequest,
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user),

):
    """
    Actualiza el estado de una aprobación de respuesta asignada a un usuario.

    Este endpoint permite que un usuario apruebe o rechace una respuesta específica. 
    Si la aprobación es válida, se envían correos según la configuración del formulario y se 
    ejecutan validaciones adicionales para verificar si el flujo de aprobación se ha completado.

    Parámetros:
    ----------
    request : Request
        Objeto de solicitud HTTP para contexto adicional (como host, headers, etc.).

    response_id : int
        ID de la respuesta que se desea aprobar/rechazar.

    update_data : UpdateResponseApprovalRequest
        Datos enviados por el usuario para actualizar el estado de la aprobación:
        - `status`: "aprobado" o "rechazado".
        - `message`: mensaje opcional del aprobador.
        - `reviewed_at`: fecha de revisión.
        - `selectedSequence`: número de secuencia de la aprobación.

    db : Session
        Sesión activa de la base de datos.

    current_user : User
        Usuario autenticado que realiza la aprobación.

    Retorna:
    -------
    dict
        Mensaje de éxito junto con los datos de la aprobación actualizada.

    Errores:
    -------
    - 403 FORBIDDEN: Si el usuario no está autenticado.
    - 404 NOT FOUND: Si no se encuentra el registro `ResponseApproval` correspondiente.
    - 400 BAD REQUEST: Si los datos son inválidos o hay conflictos.
    """
    try:
        print("Datos recibidos:", update_data)
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have permission to get options"
            )
        updated_response_approval = await update_response_approval_status(
            response_id=response_id,
            user_id=current_user.id,
            update_data=update_data,
            db=db,
            current_user=current_user,
            request = request
        )
        return {"message": "ResponseApproval updated successfully", "response_approval": updated_response_approval}
    except HTTPException as e:
        raise e



@router.put("/form-approvals/{id}/set-not-is_active")
def set_is_active_false(id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Buscar el FormApproval por ID
    """
    Desactiva un aprobador (`FormApproval`) estableciendo `is_active = False`.

    Este endpoint permite marcar un aprobador como inactivo, sin eliminar el registro de la base de datos.
    Es útil cuando se desea reemplazar o remover temporalmente un aprobador del flujo de aprobación.

    Parámetros:
    -----------
    id : int
        ID del registro `FormApproval` que se desea desactivar.

    db : Session
        Sesión activa de la base de datos.

    current_user : User
        Usuario autenticado. Se requiere autenticación para ejecutar esta acción.


    Errores:
    --------
    - 403 FORBIDDEN: Si el usuario no está autenticado.
    - 404 NOT FOUND: Si el `FormApproval` no existe.
    """
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get options"
            )
    else: 
        form_approval = db.query(FormApproval).filter(FormApproval.id == id).first()
        
        if not form_approval:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FormApproval no encontrado")
        

        form_approval.is_active = False
        db.commit()  # Confirmar la transacción
        db.refresh(form_approval)  # Refrescar el objeto para obtener los datos actualizados
        
        return {"message": "is_mandatory actualizado a False", "form_approval": form_approval}



@router.post("/approval-requirements/create")
def create_approval_requirements(
    data: ApprovalRequirementsCreateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Crea requisitos de aprobación para formularios específicos.
    
    - Requiere que el usuario actual esté autenticado.
    - Valida la existencia de formularios y usuarios.
    - Guarda los requisitos de aprobación con la información de:
        - Formulario principal
        - Usuario aprobador
        - Formulario requerido como prerequisito
        - Si debe seguir línea de aprobación
        - Estado de diligenciamiento
    
    Args:
        data (ApprovalRequirementsCreateSchema): Lista de requisitos de aprobación.
            - requirements: Lista con:
                - form_id: ID del formulario principal
                - approver_id: ID del usuario aprobador
                - required_form_id: ID del formulario requerido como prerequisito
                - linea_aprobacion: Si debe seguir secuencia obligatoria (default: True)
        db (Session): Sesión de la base de datos inyectada por dependencia.
        current_user (User): Usuario autenticado actual.
    
    Returns:
        dict: Resultado de la operación con IDs creados y resumen.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission"
        )
    
    try:
        created_ids = save_approval_requirements(data, db)
        
        return {
            "success": True,
            "message": "Requisitos de aprobación creados exitosamente",
            "created_requirement_ids": created_ids,
            "summary": {
                "total_requirements_created": len(created_ids),
                "requirements_with_approval_line": len([
                    req for req in data.requirements if req.linea_aprobacion
                ]),
           
            }
        }
    
    except HTTPException as e:
        # Re-raise HTTP exceptions
        raise e
    except Exception as e:
        # Manejo de errores inesperados
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )



@router.put("/form-approvals/bulk-update")
def bulk_update_form_approvals(data: BulkUpdateFormApprovals, db: Session = Depends(get_db)):
    """
    Actualiza masivamente registros de aprobación (`FormApproval`) asociados a formularios.

    Este endpoint permite modificar varios aprobadores simultáneamente.
    Si se detecta un cambio en los campos clave (`user_id`, `sequence_number` o `is_mandatory`),
    se inactiva el registro original y se crea uno nuevo con los datos actualizados.

    Además, se actualizan las entradas de `ResponseApproval` pendientes correspondientes
    para reflejar correctamente los nuevos aprobadores o secuencias.

    Parámetros:
    -----------
    data : BulkUpdateFormApprovals
        Contiene una lista de actualizaciones con los campos:
        - `id`: ID del `FormApproval` a actualizar.
        - `user_id`: Nuevo ID del usuario aprobador.
        - `sequence_number`: Número de secuencia del aprobador.
        - `is_mandatory`: Si la aprobación es obligatoria.
        - `deadline_days`: Días límite para aprobar.

    db : Session
        Sesión activa de base de datos.

    Retorna:
    --------
    dict:
        Mensaje de confirmación.
        ```json
        {
            "message": "FormApprovals updated successfully"
        }
        ```

    Errores:
    --------
    - 404 NOT FOUND: Si alguno de los `FormApproval` especificados no existe o está inactivo.

    Consideraciones:
    ----------------
    - Las aprobaciones existentes no se eliminan; se inactivan (`is_active = False`) por trazabilidad.
    - Las respuestas pendientes (`ResponseApproval`) se reasignan al nuevo aprobador automáticamente si aplica.
    """
    for update in data.updates:
        existing = db.query(FormApproval).filter(FormApproval.id == update.id, FormApproval.is_active == True).first()
        if not existing:
            raise HTTPException(status_code=404, detail=f"FormApproval with id {update.id} not found")

        user_changed = existing.user_id != update.user_id
        seq_changed = existing.sequence_number != update.sequence_number
        mandatory_changed = existing.is_mandatory != update.is_mandatory

        if user_changed or seq_changed or mandatory_changed:
            # Desactivar el actual
            existing.is_active = False

            # Crear el nuevo FormApproval
            new_approval = FormApproval(
                form_id=existing.form_id,
                user_id=update.user_id,
                sequence_number=update.sequence_number or existing.sequence_number,
                is_mandatory=update.is_mandatory if update.is_mandatory is not None else existing.is_mandatory,
                deadline_days=update.deadline_days if update.deadline_days is not None else existing.deadline_days,
                is_active=True
            )
            db.add(new_approval)

            # Actualizar ResponseApproval
            pending_responses = (
                db.query(ResponseApproval)
                .join(Response)
                .filter(
                    Response.form_id == existing.form_id,
                    ResponseApproval.user_id == existing.user_id,
                    ResponseApproval.sequence_number == existing.sequence_number,
                    ResponseApproval.status == ApprovalStatus.pendiente
                )
                .all()
            )

            for ra in pending_responses:
                ra.user_id = update.user_id
                ra.sequence_number = update.sequence_number
                ra.is_mandatory = update.is_mandatory

        else:
            # Si no hubo cambio crítico, solo actualiza campos simples
            if update.sequence_number is not None:
                existing.sequence_number = update.sequence_number
            if update.is_mandatory is not None:
                existing.is_mandatory = update.is_mandatory
            if update.deadline_days is not None:
                existing.deadline_days = update.deadline_days

    db.commit()
    return {"message": "FormApprovals updated successfully"}



@router.get("/get_form_with_approvers/{form_id}/with-approvers", response_model=FormWithApproversResponse)
def get_form_with_approvers(
    form_id: int,
    db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    Obtiene los datos básicos de un formulario junto con la lista de aprobadores activos asignados.

    Este endpoint es útil para mostrar al usuario (usualmente administrador o creador del formulario)
    qué usuarios están asignados como aprobadores y en qué orden.

    Parámetros:
    ----------
    form_id : int
        ID del formulario que se desea consultar.

    db : Session
        Sesión activa de la base de datos.

    current_user : User
        Usuario autenticado que realiza la consulta.

    Retorna:
    --------
    FormWithApproversResponse
        Información básica del formulario y lista de aprobadores activos (ordenados por secuencia).

    Errores:
    --------
    - 403 FORBIDDEN: Si el usuario no está autenticado.
    - 404 NOT FOUND: Si no se encuentra el formulario.
    """
    if current_user == None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to get options"
            )
    else: 
        form = db.query(Form).filter(Form.id == form_id).first()
        if not form:
            raise HTTPException(status_code=404, detail="Form not found")

        # Solo autorizadores activos
        approvals = (
            db.query(FormApproval)
            .filter(FormApproval.form_id == form_id, FormApproval.is_active == True)
            .join(FormApproval.user)
            .all()
        )

        form_data = {
            "id": form.id,
            "title": form.title,
            "description": form.description,
            "format_type": form.format_type.value,
            
            "approvers": approvals
        }

        return form_data



@router.get("/users/forms_by_approver")
def get_user_forms_by_approver(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retorna los formularios donde el usuario autenticado es aprobador activo,
    incluyendo información sobre el proceso de aprobación.
    
    - **Requiere autenticación.**
    - **Código 200**: Lista de formularios con información de aprobación.
    - **Código 403**: Usuario sin permisos (no autenticado).
    - **Código 404**: No se encontraron formularios donde sea aprobador.
    - **Código 500**: Error interno del servidor.
    """
    try:
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have permission to get approval forms"
            )
        
        forms_approval_info = get_forms_by_approver(db, current_user.id)
        
        if not forms_approval_info:
            raise HTTPException(
                status_code=404, 
                detail="No se encontraron formularios donde sea aprobador activo"
            )
        
        return forms_approval_info
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def save_approval_requirements(data: ApprovalRequirementsCreateSchema, db: Session):
    """
    Guarda los requisitos de aprobación en la base de datos.
    
    - Valida que existan los formularios y usuarios referenciados.
    - Verifica que no existan duplicados activos.
    - Crea nuevos registros en la tabla approval_requirements.
    
    Args:
        data (ApprovalRequirementsCreateSchema): Datos de los requisitos a guardar.
        db (Session): Sesión de la base de datos.
    
    Returns:
        List[int]: Lista de IDs de los requisitos creados.
    """
    created_requirement_ids = []
    
    for requirement in data.requirements:
        # Validar que existe el formulario principal
        main_form = db.query(Form).filter(Form.id == requirement.form_id).first()
        if not main_form:
            raise HTTPException(
                status_code=404, 
                detail=f"Formulario principal con ID {requirement.form_id} no encontrado"
            )
        
        # Validar que existe el usuario aprobador
        approver = db.query(User).filter(User.id == requirement.approver_id).first()
        if not approver:
            raise HTTPException(
                status_code=404, 
                detail=f"Usuario aprobador con ID {requirement.approver_id} no encontrado"
            )
        
        # Validar que existe el formulario requerido
        required_form = db.query(Form).filter(Form.id == requirement.required_form_id).first()
        if not required_form:
            raise HTTPException(
                status_code=404, 
                detail=f"Formulario requerido con ID {requirement.required_form_id} no encontrado"
            )
        
        # Verificar si ya existe un requisito similar (para evitar duplicados)
        existing_requirement = db.query(ApprovalRequirement).filter(
            ApprovalRequirement.form_id == requirement.form_id,
            ApprovalRequirement.approver_id == requirement.approver_id,
            ApprovalRequirement.required_form_id == requirement.required_form_id
        ).first()
        
        if existing_requirement:
            # Si existe, puedes decidir si actualizar o saltar
            # Por ahora saltamos los duplicados
            continue
        
        # Crear nuevo requisito de aprobación
        new_requirement = ApprovalRequirement(
            form_id=requirement.form_id,
            approver_id=requirement.approver_id,
            required_form_id=requirement.required_form_id,
            linea_aprobacion=requirement.linea_aprobacion,
        )
        
        db.add(new_requirement)
        db.flush()  # Para obtener el ID sin hacer commit
        created_requirement_ids.append(new_requirement.id)
    
    db.commit()
    return created_requirement_ids


        
def save_response_approval_requirements(
    data: ResponseApprovalRequirementsCreateSchema, 
    db: Session
) -> List[int]:
    """
    Guarda los requisitos de aprobación específicos para respuestas.
    
    Args:
        data: Schema con la lista de requisitos de respuesta
        db: Sesión de la base de datos
        
    Returns:
        List[int]: Lista de IDs creados
        
    Raises:
        HTTPException: Si hay errores de validación o guardado
    """
    created_ids = []
    
    try:
        for req_data in data.requirements:
            # Validar que la respuesta existe
            response = db.query(Response).filter(
                Response.id == req_data.response_id
            ).first()
            if not response:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Response with ID {req_data.response_id} not found"
                )
            
            # Validar que el approval requirement existe
            approval_req = db.query(ApprovalRequirement).filter(
                ApprovalRequirement.id == req_data.approval_requirement_id
            ).first()
            if not approval_req:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Approval requirement with ID {req_data.approval_requirement_id} not found"
                )
            
            # Validar fulfilling_response_id si se proporciona
            if req_data.fulfilling_response_id:
                fulfilling_response = db.query(Response).filter(
                    Response.id == req_data.fulfilling_response_id
                ).first()
                if not fulfilling_response:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Fulfilling response with ID {req_data.fulfilling_response_id} not found"
                    )
            
            # Verificar si ya existe este requisito para esta respuesta
            existing = db.query(ResponseApprovalRequirement).filter(
                ResponseApprovalRequirement.response_id == req_data.response_id,
                ResponseApprovalRequirement.approval_requirement_id == req_data.approval_requirement_id
            ).first()
            
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Response approval requirement already exists for response {req_data.response_id} and approval requirement {req_data.approval_requirement_id}"
                )
            
            # Crear el nuevo registro
            new_requirement = ResponseApprovalRequirement(
                response_id=req_data.response_id,
                approval_requirement_id=req_data.approval_requirement_id,
                fulfilling_response_id=req_data.fulfilling_response_id,
                is_fulfilled=req_data.is_fulfilled
            )
            
            db.add(new_requirement)
            db.flush()  # Para obtener el ID
            created_ids.append(new_requirement.id)
        
        db.commit()
        return created_ids
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error saving response approval requirements: {str(e)}"
        )

# Endpoint
@router.post("/response-approval-requirements/create")
def create_response_approval_requirements(
    data: ResponseApprovalRequirementsCreateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Crea requisitos de aprobación específicos para respuestas de formularios.
    
    - Requiere que el usuario actual esté autenticado.
    - Valida la existencia de respuestas y requisitos de aprobación.
    - Guarda los requisitos específicos para cada respuesta con:
        - Respuesta específica que debe cumplir el requisito
        - Requisito de aprobación base desde la configuración del formulario
        - Respuesta que cumple el requisito (opcional)
        - Estado de cumplimiento del requisito
    
    Args:
        data (ResponseApprovalRequirementsCreateSchema): Lista de requisitos de respuesta.
            - requirements: Lista con:
                - response_id: ID de la respuesta que debe cumplir el requisito
                - approval_requirement_id: ID del requisito de aprobación base
                - fulfilling_response_id: ID de la respuesta que cumple el requisito (opcional)
                - is_fulfilled: Estado del requisito (default: False)
        db (Session): Sesión de la base de datos inyectada por dependencia.
        current_user (User): Usuario autenticado actual.
    
    Returns:
        dict: Resultado de la operación con IDs creados y resumen.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission"
        )
    
    try:
        created_ids = save_response_approval_requirements(data, db)
        
        return {
            "success": True,
            "message": "Requisitos de aprobación de respuestas creados exitosamente",
            "created_requirement_ids": created_ids,
            "summary": {
                "total_requirements_created": len(created_ids),
                "fulfilled_requirements": len([
                    req for req in data.requirements if req.is_fulfilled
                ]),
                "pending_requirements": len([
                    req for req in data.requirements if not req.is_fulfilled
                ])
            }
        }
    
    except HTTPException as e:
        # Re-raise HTTP exceptions
        raise e
    except Exception as e:
        # Manejo de errores inesperados
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )

# Endpoint adicional para actualizar el estado de cumplimiento
@router.put("/response-approval-requirements/{requirement_id}/fulfill")
def fulfill_response_approval_requirement(
    requirement_id: int,
    fulfilling_response_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Marca un requisito de aprobación de respuesta como cumplido.
    
    Args:
        requirement_id: ID del requisito de respuesta a actualizar
        fulfilling_response_id: ID de la respuesta que cumple el requisito
        db: Sesión de la base de datos
        current_user: Usuario autenticado actual
    
    Returns:
        dict: Resultado de la operación
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission"
        )
    
    try:
        # Buscar el requisito
        requirement = db.query(ResponseApprovalRequirement).filter(
            ResponseApprovalRequirement.id == requirement_id
        ).first()
        
        if not requirement:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Response approval requirement with ID {requirement_id} not found"
            )
        
        # Validar que la respuesta que cumple el requisito existe
        fulfilling_response = db.query(Response).filter(
            Response.id == fulfilling_response_id
        ).first()
        
        if not fulfilling_response:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Fulfilling response with ID {fulfilling_response_id} not found"
            )
        
        # Actualizar el requisito
        requirement.fulfilling_response_id = fulfilling_response_id
        requirement.is_fulfilled = True
        
        db.commit()
        
        return {
            "success": True,
            "message": "Requisito de aprobación marcado como cumplido exitosamente",
            "requirement_id": requirement_id,
            "fulfilling_response_id": fulfilling_response_id
        }
    
    except HTTPException as e:
        raise e
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )
        


def get_approval_requirements_by_response(db: Session, response_id: int):
    """
    Obtiene los requisitos de aprobación específicos para una respuesta,
    incluyendo si ya están cumplidos o no.
    """
    response = db.query(Response).filter(Response.id == response_id).first()
    if not response:
        return []

    # Obtener los requisitos base del formulario
    base_requirements = db.query(ApprovalRequirement).filter(
        ApprovalRequirement.form_id == response.form_id
    ).all()

    result = []
    for base_req in base_requirements:
        # Buscar si ya existe un registro específico para esta respuesta
        response_req = db.query(ResponseApprovalRequirement).filter(
            ResponseApprovalRequirement.response_id == response_id,
            ResponseApprovalRequirement.approval_requirement_id == base_req.id
        ).first()

        # Si no existe, crearlo automáticamente
        if not response_req:
            response_req = ResponseApprovalRequirement(
                response_id=response_id,
                approval_requirement_id=base_req.id,
                fulfilling_response_id=None,
                is_fulfilled=False
            )
            db.add(response_req)
            db.flush()

        # Construir la respuesta
        requirement_data = {
            "requirement_id": base_req.id,
            "response_requirement_id": response_req.id,
            "required_form": {
                "form_id": base_req.required_form_id,
                "form_title": base_req.required_form.title,
                "form_description": base_req.required_form.description
            },
            "linea_aprobacion": base_req.linea_aprobacion,
            "form_diligenciado": response_req.is_fulfilled,
            "fulfilling_response_id": response_req.fulfilling_response_id,
            "approver": {
                "user_id": base_req.approver_id,
                "name": base_req.approver.name,
                "email": base_req.approver.email,
                "num_document": base_req.approver.num_document
            }
        }
        result.append(requirement_data)

    db.commit()
    return result


