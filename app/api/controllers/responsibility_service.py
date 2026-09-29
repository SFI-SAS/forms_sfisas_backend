from sqlalchemy.orm import Session
from sqlalchemy import and_, false as sa_false, select
from typing import List, Dict, Any
import logging
from datetime import datetime

from app.models import ApprovalStatus, Form, FormApproval, FormApprovalNotification, FormModerators, FormSchedule, Response, ResponseApproval, User
class ResponsibilityTransferService:
    """
    Servicio para transferir responsabilidades de un usuario a otro
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.logger = logging.getLogger(__name__)
    
    # ── Acotar a unos formatos ─────────────────────────────────────────
    #
    # Todos los `_transfer_*` aceptan `form_ids`: None = todos (la
    # transferencia completa), una lista = SOLO esos. Antes se intentaba al
    # reves —pasando los formatos a EXCLUIR—, lo que obligaba a construir una
    # lista con todos los formatos del sistema menos los pedidos.

    def _acotar_a_formatos(self, consulta, columna_form_id, form_ids):
        """Aplica el filtro por formato, si lo hay."""
        if form_ids is None:
            return consulta
        if not form_ids:
            # Lista vacia: no hay nada que transferir. Se devuelve una
            # consulta que no encuentra nada, no "todos".
            return consulta.filter(sa_false())
        return consulta.filter(columna_form_id.in_(form_ids))

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
                    "moderators": 0,
                    # Aprobaciones PENDIENTES de respuestas ya enviadas. Sin
                    # esto, esas respuestas se quedaban esperando a alguien que
                    # ya no tiene el cargo, sin forma de desatascarlas.
                    "pending_approvals": 0
                },
                "skipped_duplicates": {
                    "schedules": 0,
                    "approvals": 0,
                    "notifications": 0,
                    "moderators": 0,
                    "pending_approvals": 0
                },
                # Avisos de cosas que se movieron pero hay que mirar a mano.
                "warnings": {
                    # Pendientes que exigen firma FACIAL: el que las reciba
                    # tiene que tener registro facial o no podra aprobarlas.
                    "pending_approvals_facial": 0,
                    # Recibidores que colgaban del usuario que se va y ahora
                    # cuelgan del que llega.
                    "receiver_chains_rewired": 0
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

            # 5. Transferir las aprobaciones PENDIENTES
            pendientes_result = self._transfer_pending_response_approvals(
                from_user_id, to_user_id
            )
            transfer_summary["transferred"]["pending_approvals"] = pendientes_result["transferred"]
            transfer_summary["skipped_duplicates"]["pending_approvals"] = pendientes_result["skipped"]
            transfer_summary["warnings"]["pending_approvals_facial"] = pendientes_result["facial"]
            transfer_summary["warnings"]["receiver_chains_rewired"] = pendientes_result["chains"]
            
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
        to_user_id: int,
        form_ids: List[int] = None,
    ) -> Dict[str, int]:
        """
        Transfiere FormSchedule automáticamente detectando duplicados
        """
        # Obtener schedules del usuario origen
        schedules_to_transfer = self._acotar_a_formatos(
            self.db.query(FormSchedule).filter(FormSchedule.user_id == from_user_id),
            FormSchedule.form_id, form_ids,
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
        to_user_id: int,
        form_ids: List[int] = None,
    ) -> Dict[str, int]:
        """
        Transfiere FormApproval permitiendo duplicados por sequence_number diferente
        """
        # Obtener approvals del usuario origen
        approvals_to_transfer = self._acotar_a_formatos(
            self.db.query(FormApproval).filter(FormApproval.user_id == from_user_id),
            FormApproval.form_id, form_ids,
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
        to_user_id: int,
        form_ids: List[int] = None,
    ) -> Dict[str, int]:
        """
        Transfiere FormApprovalNotification automáticamente detectando duplicados
        """
        # Obtener notifications del usuario origen
        notifications_to_transfer = self._acotar_a_formatos(
            self.db.query(FormApprovalNotification).filter(
                FormApprovalNotification.user_id == from_user_id
            ),
            FormApprovalNotification.form_id, form_ids,
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
        to_user_id: int,
        form_ids: List[int] = None,
    ) -> Dict[str, int]:
        """
        Transfiere FormModerators automáticamente detectando duplicados
        """
        # Obtener moderators del usuario origen
        moderators_to_transfer = self._acotar_a_formatos(
            self.db.query(FormModerators).filter(FormModerators.user_id == from_user_id),
            FormModerators.form_id, form_ids,
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
    
    def _transfer_pending_response_approvals(
        self,
        from_user_id: int,
        to_user_id: int,
        form_ids: List[int] = None,
    ) -> Dict[str, int]:
        """Pasa al usuario destino las aprobaciones que siguen PENDIENTES.

        Solo las pendientes. Las que ya se aprobaron o se rechazaron son
        historia: dicen quién firmó qué y cuándo, y reescribirlas sería falsear
        lo que pasó. Por eso aquí no se tocan.

        Devuelve, además de los contadores de siempre:
          · `facial`: cuántas de las movidas exigen firma FACIAL. El que las
            reciba necesita registro facial o no podrá aprobarlas, y eso no se
            arregla solo.
          · `chains`: cuántos recibidores colgaban del que se va y se
            reengancharon al que llega (ver abajo).
        """
        consulta = self.db.query(ResponseApproval).filter(
            ResponseApproval.user_id == from_user_id,
            ResponseApproval.status == ApprovalStatus.pendiente,
        )
        if form_ids is not None:
            # La aprobación no sabe de qué formato es: hay que ir por su
            # respuesta.
            if not form_ids:
                consulta = consulta.filter(sa_false())
            else:
                respuestas = self.db.query(Response.id).filter(
                    Response.form_id.in_(form_ids)
                ).subquery()
                consulta = consulta.filter(
                    ResponseApproval.response_id.in_(select(respuestas.c.id))
                )
        pendientes = consulta.all()

        transferred_count = 0
        skipped_count = 0
        facial_count = 0
        respuestas_tocadas = set()

        for aprobacion in pendientes:
            # ¿El destino ya es participante de esta respuesta en el mismo paso?
            existente = self.db.query(ResponseApproval).filter(
                and_(
                    ResponseApproval.response_id == aprobacion.response_id,
                    ResponseApproval.user_id == to_user_id,
                    ResponseApproval.sequence_number == aprobacion.sequence_number,
                    ResponseApproval.id != aprobacion.id,
                )
            ).first()

            respuestas_tocadas.add(aprobacion.response_id)

            if existente:
                # Ya le toca a él en ese paso: la fila del origen sobra. Se
                # borra, como hace el resto de la transferencia con los
                # duplicados.
                self.logger.info(
                    "Eliminada aprobación pendiente duplicada: response_id=%s, paso=%s",
                    aprobacion.response_id, aprobacion.sequence_number,
                )
                self.db.delete(aprobacion)
                skipped_count += 1
                continue

            aprobacion.user_id = to_user_id
            if (aprobacion.firm_mode or "") == "facial":
                facial_count += 1
            transferred_count += 1
            self.logger.info(
                "Transferida aprobación pendiente: response_id=%s, paso=%s, papel=%s",
                aprobacion.response_id, aprobacion.sequence_number,
                aprobacion.participant_role,
            )

        chains = self._rewire_receiver_chains(
            from_user_id, to_user_id, respuestas_tocadas
        )

        return {
            "transferred": transferred_count,
            "skipped": skipped_count,
            "facial": facial_count,
            "chains": chains,
        }

    def _rewire_receiver_chains(
        self,
        from_user_id: int,
        to_user_id: int,
        response_ids: set
    ) -> int:
        """Reengancha los recibidores que colgaban del usuario que se va.

        Un recibidor guarda de quién recibe en `receives_from_user_ids`, y el
        motor de la cadena compara esa lista contra el id del aprobador. Si se
        mueve la aprobación de A a B y la lista sigue diciendo A, el recibidor
        se queda esperando a alguien que ya no participa: el formato no llega
        nunca a su destino.

        Solo se toca una respuesta cuando A ya NO tiene ninguna fila en ella. Si
        le queda alguna —por ejemplo una que ya aprobó—, el recibidor sigue
        colgando de A con razón: A aprobó eso de verdad.
        """
        reenganchados = 0

        for response_id in response_ids:
            le_queda_algo = self.db.query(ResponseApproval.id).filter(
                ResponseApproval.response_id == response_id,
                ResponseApproval.user_id == from_user_id,
            ).first()
            if le_queda_algo:
                continue

            participantes = self.db.query(ResponseApproval).filter(
                ResponseApproval.response_id == response_id
            ).all()

            for participante in participantes:
                lista = getattr(participante, "receives_from_user_ids", None) or []
                if not isinstance(lista, list):
                    continue
                # Los ids pueden venir como número o como texto según quién
                # escribió la lista.
                def mismo(x):
                    try:
                        return int(x) == int(from_user_id)
                    except (TypeError, ValueError):
                        return False
                if not any(mismo(x) for x in lista):
                    continue

                nueva, vistos = [], set()
                for x in lista:
                    valor = to_user_id if mismo(x) else x
                    try:
                        clave = int(valor)
                    except (TypeError, ValueError):
                        clave = valor
                    if clave in vistos:
                        continue
                    vistos.add(clave)
                    nueva.append(valor)

                # Se asigna una lista NUEVA: la columna es JSON y editarla en
                # el sitio no se detecta como cambio.
                participante.receives_from_user_ids = nueva
                reenganchados += 1
                self.logger.info(
                    "Recibidor reenganchado: response_id=%s, usuario=%s",
                    response_id, participante.user_id,
                )

        return reenganchados

    def get_user_responsibilities(self, user_id: int) -> Dict[str, List]:
        """
        Obtiene todas las responsabilidades de un usuario, incluyendo la información completa del formulario.
        """
        responsibilities = {
            "schedules": [],
            "approvals": [],
            "notifications": [],
            "moderators": [],
            # Aprobaciones PENDIENTES de respuestas ya enviadas. Van aparte de
            # "approvals": aquellas son la plantilla del formato (a quién le
            # tocará), estas son trabajo concreto parado esperando a esta
            # persona.
            "pending_approvals": []
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

        # Aprobaciones PENDIENTES de respuestas ya enviadas
        pendientes = (
            self.db.query(ResponseApproval, Response, Form)
            .join(Response, Response.id == ResponseApproval.response_id)
            .join(Form, Form.id == Response.form_id)
            .filter(
                ResponseApproval.user_id == user_id,
                ResponseApproval.status == ApprovalStatus.pendiente,
            )
            .order_by(ResponseApproval.id.desc())
            .all()
        )

        for aprobacion, respuesta, form in pendientes:
            responsibilities["pending_approvals"].append({
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
                "response_id": respuesta.id,
                "submitted_at": respuesta.submitted_at,
                "sequence_number": aprobacion.sequence_number,
                "participant_role": aprobacion.participant_role,
                # Quien la reciba tiene que poder firmar así.
                "firm_mode": aprobacion.firm_mode,
            })

        return responsibilities

    def transfer_specific_responsibilities(
        self,
        from_user_id: int,
        to_user_id: int,
        form_ids: List[int],
        responsibility_types: List[str] = None
    ) -> Dict[str, Any]:
        """Transfiere responsabilidades SOLO de los formatos indicados.

        Args:
            from_user_id: usuario que las suelta
            to_user_id: usuario que las recibe
            form_ids: los formatos a los que se acota (obligatorio)
            responsibility_types: qué transferir. Por defecto, todo:
                ['schedules', 'approvals', 'notifications', 'moderators',
                 'pending_approvals']

        Esta ruta nunca llegó a funcionar: calculaba la lista de formatos a
        EXCLUIR y se la pasaba como tercer argumento a funciones que solo
        aceptaban dos, así que reventaba con TypeError y el endpoint devolvía un
        400 genérico. Además guardaba el diccionario de resultados entero donde
        iba el contador.
        """
        # Todo lo que se puede transferir.
        TIPOS = ('schedules', 'approvals', 'notifications', 'moderators',
                 'pending_approvals')

        if responsibility_types is None:
            responsibility_types = list(TIPOS)

        desconocidos = [t for t in responsibility_types if t not in TIPOS]
        if desconocidos:
            raise ValueError(
                "Tipos de responsabilidad desconocidos: %s. Válidos: %s"
                % (", ".join(desconocidos), ", ".join(TIPOS))
            )

        from_user = self.db.query(User).filter(User.id == from_user_id).first()
        to_user = self.db.query(User).filter(User.id == to_user_id).first()
        if not from_user or not to_user:
            raise ValueError("Uno o ambos usuarios no existen")

        if not form_ids:
            raise ValueError("Hay que indicar al menos un formato")

        transfer_summary = {
            "from_user_id": from_user_id,
            "to_user_id": to_user_id,
            "from_user": from_user.name,
            "to_user": to_user.name,
            "form_ids": form_ids,
            "responsibility_types": responsibility_types,
            "transferred": {t: 0 for t in TIPOS},
            "skipped_duplicates": {t: 0 for t in TIPOS},
            "warnings": {
                "pending_approvals_facial": 0,
                "receiver_chains_rewired": 0,
            },
        }

        trabajos = (
            ('schedules', self._transfer_form_schedules),
            ('approvals', self._transfer_form_approvals),
            ('notifications', self._transfer_form_notifications),
            ('moderators', self._transfer_form_moderators),
            ('pending_approvals', self._transfer_pending_response_approvals),
        )

        try:
            for tipo, hacer in trabajos:
                if tipo not in responsibility_types:
                    continue
                # A cada uno se le pasan los formatos PEDIDOS; dentro, cada
                # helper sabe por qué columna acotar.
                resultado = hacer(from_user_id, to_user_id, form_ids)
                transfer_summary["transferred"][tipo] = resultado["transferred"]
                transfer_summary["skipped_duplicates"][tipo] = resultado["skipped"]
                if tipo == 'pending_approvals':
                    transfer_summary["warnings"]["pending_approvals_facial"] = resultado["facial"]
                    transfer_summary["warnings"]["receiver_chains_rewired"] = resultado["chains"]

            self.db.commit()
            self.logger.info("Transferencia por formatos completada: %s", transfer_summary)
            return transfer_summary

        except Exception as e:
            self.db.rollback()
            self.logger.error("Error en transferencia por formatos: %s", e)
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
                    # Aquí también se pasaba un tercer argumento
                    # (`exclude_forms`) que esta función nunca ha aceptado. Si
                    # se quiere acotar, el camino es `form_ids`, que es lo que
                    # entiende la transferencia por formatos.
                    result = self.transfer_all_responsibilities(
                        transfer["from_user_id"],
                        transfer["to_user_id"],
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

