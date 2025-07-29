from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Dict, Any
import logging
from datetime import datetime

from app.models import ApprovalStatus, Form, FormApproval, FormApprovalNotification, FormModerators, FormSchedule, ResponseApproval, User
class ResponsibilityTransferService:
    """
    Servicio para transferir responsabilidades de un usuario a otro
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.logger = logging.getLogger(__name__)
    
    def transfer_all_responsibilities(
        self, 
        from_user_id: int, 
        to_user_id: int
    ) -> Dict[str, Any]:
        """
        Transfiere todas las responsabilidades de un usuario a otro
        Automáticamente detecta duplicados y los maneja inteligentemente
        
        Args:
            from_user_id: ID del usuario que transfiere
            to_user_id: ID del usuario que recibe
        
        Returns:
            Dict con el resumen de la transferencia
        """
        try:
            # Validar que los usuarios existan
            from_user = self.db.query(User).filter(User.id == from_user_id).first()
            to_user = self.db.query(User).filter(User.id == to_user_id).first()
            
            if not from_user or not to_user:
                raise ValueError("Uno o ambos usuarios no existen")
            
            transfer_summary = {
                "from_user": from_user.name,
                "to_user": to_user.name,
                "transferred": {
                    "schedules": 0,
                    "approvals": 0,
                    "notifications": 0,
                    "moderators": 0
                },
                "skipped_duplicates": {
                    "schedules": 0,
                    "approvals": 0,
                    "notifications": 0,
                    "moderators": 0
                },
                "details": []
            }
            
            # 1. Transferir FormSchedule
            schedules_result = self._transfer_form_schedules(from_user_id, to_user_id)
            transfer_summary["transferred"]["schedules"] = schedules_result["transferred"]
            transfer_summary["skipped_duplicates"]["schedules"] = schedules_result["skipped"]
            
            # 2. Transferir FormApproval
            approvals_result = self._transfer_form_approvals(from_user_id, to_user_id)
            transfer_summary["transferred"]["approvals"] = approvals_result["transferred"]
            transfer_summary["skipped_duplicates"]["approvals"] = approvals_result["skipped"]
            
            # 3. Transferir FormApprovalNotification
            notifications_result = self._transfer_form_notifications(from_user_id, to_user_id)
            transfer_summary["transferred"]["notifications"] = notifications_result["transferred"]
            transfer_summary["skipped_duplicates"]["notifications"] = notifications_result["skipped"]
            
            # 4. Transferir FormModerators
            moderators_result = self._transfer_form_moderators(from_user_id, to_user_id)
            transfer_summary["transferred"]["moderators"] = moderators_result["transferred"]
            transfer_summary["skipped_duplicates"]["moderators"] = moderators_result["skipped"]
            
            self.db.commit()
            
            self.logger.info(f"Transferencia completada: {transfer_summary}")
            return transfer_summary
            
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Error en transferencia: {str(e)}")
            raise e
    
    def _transfer_form_schedules(
        self, 
        from_user_id: int, 
        to_user_id: int
    ) -> Dict[str, int]:
        """
        Transfiere FormSchedule automáticamente detectando duplicados
        """
        # Obtener schedules del usuario origen
        schedules_to_transfer = self.db.query(FormSchedule).filter(
            FormSchedule.user_id == from_user_id
        ).all()
        
        transferred_count = 0
        skipped_count = 0
        
        for schedule in schedules_to_transfer:
            # Verificar si ya existe en el usuario destino
            existing = self.db.query(FormSchedule).filter(
                and_(
                    FormSchedule.form_id == schedule.form_id,
                    FormSchedule.user_id == to_user_id,
                    FormSchedule.frequency_type == schedule.frequency_type
                )
            ).first()
            
            if not existing:
                # Transferir cambiando el user_id
                schedule.user_id = to_user_id
                transferred_count += 1
                self.logger.info(f"Transferido FormSchedule: form_id={schedule.form_id}, frequency={schedule.frequency_type}")
            else:
                # Ya existe, eliminar el del usuario origen
                self.logger.info(f"Eliminado FormSchedule duplicado: form_id={schedule.form_id} (ya existe en destino)")
                self.db.delete(schedule)
                skipped_count += 1
        
        return {"transferred": transferred_count, "skipped": skipped_count}
    
    def _transfer_form_approvals(
        self, 
        from_user_id: int, 
        to_user_id: int
    ) -> Dict[str, int]:
        """
        Transfiere FormApproval permitiendo duplicados por sequence_number diferente
        """
        # Obtener approvals del usuario origen
        approvals_to_transfer = self.db.query(FormApproval).filter(
            FormApproval.user_id == from_user_id
        ).all()
        
        transferred_count = 0
        skipped_count = 0
        
        for approval in approvals_to_transfer:
            # Verificar si ya existe exactamente la misma combinación
            existing = self.db.query(FormApproval).filter(
                and_(
                    FormApproval.form_id == approval.form_id,
                    FormApproval.user_id == to_user_id,
                    FormApproval.sequence_number == approval.sequence_number
                )
            ).first()
            
            if not existing:
                # Transferir cambiando el user_id
                approval.user_id = to_user_id
                transferred_count += 1
                self.logger.info(f"Transferido FormApproval: form_id={approval.form_id}, sequence={approval.sequence_number}")
            else:
                # Existe exactamente igual, eliminar el del usuario origen
                self.logger.info(f"Eliminado FormApproval duplicado: form_id={approval.form_id}, sequence={approval.sequence_number}")
                self.db.delete(approval)
                skipped_count += 1
        
        return {"transferred": transferred_count, "skipped": skipped_count}
    
    def _transfer_form_notifications(
        self, 
        from_user_id: int, 
        to_user_id: int
    ) -> Dict[str, int]:
        """
        Transfiere FormApprovalNotification automáticamente detectando duplicados
        """
        # Obtener notifications del usuario origen
        notifications_to_transfer = self.db.query(FormApprovalNotification).filter(
            FormApprovalNotification.user_id == from_user_id
        ).all()
        
        transferred_count = 0
        skipped_count = 0
        
        for notification in notifications_to_transfer:
            # Verificar si ya existe en el usuario destino
            existing = self.db.query(FormApprovalNotification).filter(
                and_(
                    FormApprovalNotification.form_id == notification.form_id,
                    FormApprovalNotification.user_id == to_user_id,
                    FormApprovalNotification.notify_on == notification.notify_on
                )
            ).first()
            
            if not existing:
                # Transferir cambiando el user_id
                notification.user_id = to_user_id
                transferred_count += 1
                self.logger.info(f"Transferido FormApprovalNotification: form_id={notification.form_id}, notify_on={notification.notify_on}")
            else:
                # Ya existe, eliminar el del usuario origen
                self.logger.info(f"Eliminado FormApprovalNotification duplicado: form_id={notification.form_id}")
                self.db.delete(notification)
                skipped_count += 1
        
        return {"transferred": transferred_count, "skipped": skipped_count}
    
    def _transfer_form_moderators(
        self, 
        from_user_id: int, 
        to_user_id: int
    ) -> Dict[str, int]:
        """
        Transfiere FormModerators automáticamente detectando duplicados
        """
        # Obtener moderators del usuario origen
        moderators_to_transfer = self.db.query(FormModerators).filter(
            FormModerators.user_id == from_user_id
        ).all()
        
        transferred_count = 0
        skipped_count = 0
        
        for moderator in moderators_to_transfer:
            # Verificar si ya existe en el usuario destino
            existing = self.db.query(FormModerators).filter(
                and_(
                    FormModerators.form_id == moderator.form_id,
                    FormModerators.user_id == to_user_id
                )
            ).first()
            
            if not existing:
                # Transferir cambiando el user_id
                moderator.user_id = to_user_id
                moderator.assigned_at = datetime.now()  # Actualizar fecha de asignación
                transferred_count += 1
                self.logger.info(f"Transferido FormModerators: form_id={moderator.form_id}")
            else:
                # Ya existe, eliminar el del usuario origen
                self.logger.info(f"Eliminado FormModerators duplicado: form_id={moderator.form_id}")
                self.db.delete(moderator)
                skipped_count += 1
        
        return {"transferred": transferred_count, "skipped": skipped_count}
    
    def get_user_responsibilities(self, user_id: int) -> Dict[str, List]:
        """
        Obtiene todas las responsabilidades de un usuario, incluyendo la información completa del formulario.
        """
        responsibilities = {
            "schedules": [],
            "approvals": [],
            "notifications": [],
            "moderators": []
        }

        # FormSchedule
        schedules = self.db.query(FormSchedule).join(Form).filter(
            FormSchedule.user_id == user_id
        ).all()

        for schedule in schedules:
            form = schedule.form
            responsibilities["schedules"].append({
                "form": {
                    "id": form.id,
                    "title": form.title,
                    "description": form.description,
                    "format_type": form.format_type.name if form.format_type else None,
                    "created_at": form.created_at,
                    "category": {
                        "id": form.category.id if form.category else None,
                        "name": form.category.name if form.category else None,
                        "description": form.category.description if form.category else None,
                    } if form.category else None,
                },
                "frequency_type": schedule.frequency_type,
                "status": schedule.status
            })

        # FormApproval
        approvals = self.db.query(FormApproval).join(Form).filter(
            FormApproval.user_id == user_id
        ).all()

        for approval in approvals:
            form = approval.form
            responsibilities["approvals"].append({
                "form": {
                    "id": form.id,
                    "title": form.title,
                    "description": form.description,
                    "format_type": form.format_type.name if form.format_type else None,
                    "created_at": form.created_at,
                    "category": {
                        "id": form.category.id if form.category else None,
                        "name": form.category.name if form.category else None,
                        "description": form.category.description if form.category else None,
                    } if form.category else None,
                },
                "sequence_number": approval.sequence_number,
                "is_mandatory": approval.is_mandatory,
                "is_active": approval.is_active
            })

        # FormApprovalNotification
        notifications = self.db.query(FormApprovalNotification).join(Form).filter(
            FormApprovalNotification.user_id == user_id
        ).all()

        for notification in notifications:
            form = notification.form
            responsibilities["notifications"].append({
                "form": {
                    "id": form.id,
                    "title": form.title,
                    "description": form.description,
                    "format_type": form.format_type.name if form.format_type else None,
                    "created_at": form.created_at,
                    "category": {
                        "id": form.category.id if form.category else None,
                        "name": form.category.name if form.category else None,
                        "description": form.category.description if form.category else None,
                    } if form.category else None,
                },
                "notify_on": notification.notify_on
            })

        # FormModerators
        moderators = self.db.query(FormModerators).join(Form).filter(
            FormModerators.user_id == user_id
        ).all()

        for moderator in moderators:
            form = moderator.form
            responsibilities["moderators"].append({
                "form": {
                    "id": form.id,
                    "title": form.title,
                    "description": form.description,
                    "format_type": form.format_type.name if form.format_type else None,
                    "created_at": form.created_at,
                    "category": {
                        "id": form.category.id if form.category else None,
                        "name": form.category.name if form.category else None,
                        "description": form.category.description if form.category else None,
                    } if form.category else None,
                },
                "assigned_at": moderator.assigned_at
            })

        return responsibilities

    def transfer_specific_responsibilities(
        self,
        from_user_id: int,
        to_user_id: int,
        form_ids: List[int],
        responsibility_types: List[str] = None
    ) -> Dict[str, Any]:
        """
        Transfiere responsabilidades específicas por formulario
        
        Args:
            from_user_id: Usuario origen
            to_user_id: Usuario destino
            form_ids: Lista de IDs de formularios específicos
            responsibility_types: Tipos de responsabilidades ['schedules', 'approvals', 'notifications', 'moderators']
        """
        if responsibility_types is None:
            responsibility_types = ['schedules', 'approvals', 'notifications', 'moderators']
        
        transfer_summary = {
            "from_user_id": from_user_id,
            "to_user_id": to_user_id,
            "form_ids": form_ids,
            "responsibility_types": responsibility_types,
            "transferred": {
                "schedules": 0,
                "approvals": 0,
                "notifications": 0,
                "moderators": 0
            }
        }
        
        try:
            # Crear lista de exclusión (todos los formularios EXCEPTO los especificados)
            all_form_ids = [form.id for form in self.db.query(Form.id).all()]
            exclude_forms = [fid for fid in all_form_ids if fid not in form_ids]
            
            if 'schedules' in responsibility_types:
                transfer_summary["transferred"]["schedules"] = self._transfer_form_schedules(
                    from_user_id, to_user_id, exclude_forms
                )
            
            if 'approvals' in responsibility_types:
                transfer_summary["transferred"]["approvals"] = self._transfer_form_approvals(
                    from_user_id, to_user_id, exclude_forms
                )
            
            if 'notifications' in responsibility_types:
                transfer_summary["transferred"]["notifications"] = self._transfer_form_notifications(
                    from_user_id, to_user_id, exclude_forms
                )
            
            if 'moderators' in responsibility_types:
                transfer_summary["transferred"]["moderators"] = self._transfer_form_moderators(
                    from_user_id, to_user_id, exclude_forms
                )
            
            self.db.commit()
            return transfer_summary
            
        except Exception as e:
            self.db.rollback()
            raise e


    def transfer_responsibilities_batch(
        self,
        transfers: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Realiza múltiples transferencias en lote
        
        Args:
            transfers: Lista de diccionarios con las transferencias
            [
                {
                    "from_user_id": 1,
                    "to_user_id": 2,
                    "form_ids": [1, 2, 3],  # opcional
                    "exclude_forms": [4, 5],  # opcional
                    "responsibility_types": ["schedules", "approvals"]  # opcional
                }
            ]
        """
        results = []
        
        try:
            for transfer in transfers:
                if "form_ids" in transfer:
                    # Transferencia específica
                    result = self.transfer_specific_responsibilities(
                        transfer["from_user_id"],
                        transfer["to_user_id"],
                        transfer["form_ids"],
                        transfer.get("responsibility_types", 
                                   ['schedules', 'approvals', 'notifications', 'moderators'])
                    )
                else:
                    # Transferencia completa
                    result = self.transfer_all_responsibilities(
                        transfer["from_user_id"],
                        transfer["to_user_id"],
                        transfer.get("exclude_forms", [])
                    )
                
                results.append(result)
            
            return results
            
        except Exception as e:
            self.db.rollback()
            raise e

    def get_pending_approvals_by_user(self, user_id: int) -> List[Dict]:
        """
        Obtiene las aprobaciones pendientes para un usuario
        """
        pending_approvals = self.db.query(ResponseApproval).filter(
            and_(
                ResponseApproval.user_id == user_id,
                ResponseApproval.status == ApprovalStatus.pendiente
            )
        ).all()
        
        approvals_data = []
        for approval in pending_approvals:
            approvals_data.append({
                "response_id": approval.response_id,
                "form_id": approval.response.form_id,
                "sequence_number": approval.sequence_number,
                "is_mandatory": approval.is_mandatory,
                "form_title": approval.response.form.title
            })
        
        return approvals_data

