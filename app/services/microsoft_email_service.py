import base64
import re
import httpx
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select
from app.models.activity import Activity
from app.models.agent import Agent
from app.models.comment import Comment
from app.models.microsoft import (EmailSyncConfig, EmailTicketMapping,
                                  MailboxConnection, MicrosoftToken,
                                  mailbox_team_assignments)
from app.models.task import Task, TicketBody
from app.models.ticket_attachment import TicketAttachment
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.task import TaskStatus
from app.models.workspace import Workspace
from app.schemas.microsoft import EmailAddress, EmailAttachment, EmailData
from app.services.microsoft_graph_client import MicrosoftGraphClient
from app.services.utils import get_or_create_user
from app.utils.image_processor import extract_base64_images
from app.utils.logger import logger
from app.core.exceptions import DatabaseException, MicrosoftAPIException


class MicrosoftEmailService:
    def __init__(self, db: Session, graph_client: MicrosoftGraphClient):
        self.db = db
        self.graph_client = graph_client

    def _process_html_body(self, html_content: str, attachments: List[EmailAttachment], context: str = "email") -> str:
        """Process HTML content to handle things like CID-referenced images."""
        if not html_content:
            return html_content
            
        processed_html = html_content
        
        try:
            soup = BeautifulSoup(processed_html, 'html.parser')
            cid_map = {str(att.contentId): att for att in attachments if att.is_inline and att.contentId and att.contentBytes}
            
            if cid_map:
                image_tags_updated = 0
                for img_tag in soup.find_all('img'):
                    src = img_tag.get('src')
                    if src and src.startswith('cid:'):
                        cid_value = str(src[4:].strip('<>'))
                        matching_attachment = cid_map.get(cid_value)
                        if matching_attachment:
                            content_type = matching_attachment.content_type
                            base64_data = matching_attachment.contentBytes
                            if content_type and base64_data:
                                img_tag['src'] = f"data:{content_type};base64,{base64_data}"
                                image_tags_updated += 1
                
                if image_tags_updated > 0:
                    processed_html = str(soup)
                    logger.info(f"Processed HTML for {context}, updated {image_tags_updated} CID image tags.")
            ticket_id = None
            if 'ticket' in context:
                match = re.search(r'ticket\s+(\d+)', context)
                if match:
                    ticket_id = int(match.group(1))
            if ticket_id:
                processed_html, extracted_images = extract_base64_images(processed_html, ticket_id)
                if extracted_images:
                    logger.info(f"Extracted {len(extracted_images)} base64 images from {context} for ticket {ticket_id}")
            
            return processed_html
            
        except Exception as e:
            logger.error(f"Error processing HTML for {context}: {e}", exc_info=True)
            return html_content

    async def _is_mailbox_reply_loop(self, email_content: Dict, mailbox_email: str) -> bool:
        """
        Detecta si el mailbox está procesando una respuesta interna del sistema.
        
        Casos a detectar:
        1. Mailbox aparece tanto en To como en Cc (respuesta de agente)
        2. Sender es un agente del workspace (respuesta interna)  
        3. Email tiene headers que indican que viene del propio sistema
        """
        try:
            mailbox_email_lower = mailbox_email.lower()
            sender_email = email_content.get("from", {}).get("emailAddress", {}).get("address", "")
            sender_name = email_content.get("from", {}).get("emailAddress", {}).get("name", "")
            
            logger.info(f"[LOOP DETECTION] Analyzing email from: {sender_name} <{sender_email}>")
            
            # 1. Verificar si el mailbox está en los destinatarios 'To'
            is_in_to = False
            to_recipients = email_content.get("toRecipients", [])
            for recipient in to_recipients:
                email_addr = recipient.get("emailAddress", {}).get("address", "")
                if email_addr and email_addr.lower() == mailbox_email_lower:
                    is_in_to = True
                    logger.info(f"[LOOP DETECTION] Mailbox {mailbox_email} found in TO recipients")
                    break
            
            # 2. Verificar si el mailbox está en los destinatarios 'Cc'
            is_in_cc = False
            cc_recipients = email_content.get("ccRecipients", [])
            for recipient in cc_recipients:
                email_addr = recipient.get("emailAddress", {}).get("address", "")
                if email_addr and email_addr.lower() == mailbox_email_lower:
                    is_in_cc = True
                    logger.info(f"[LOOP DETECTION] Mailbox {mailbox_email} found in CC recipients")
                    break
            
            # 3. Verificar si el sender es un agente del workspace
            is_sender_agent = await self._is_sender_internal_agent(sender_email, mailbox_email)
            
            # 4. DETECCIÓN PRINCIPAL: Si mailbox está en CC y sender es agente interno
            if is_in_cc and is_sender_agent:
                logger.warning(f"[LOOP DETECTION] 🔄 Internal agent reply detected: {sender_email} sent to mailbox {mailbox_email} (in CC)")
                return True
            
            # 5. DETECCIÓN LEGACY: Si aparece en ambos (To y Cc) - mantener lógica original
            if is_in_to and is_in_cc:
                logger.warning(f"[LOOP DETECTION] 🔄 Mailbox reply loop: {mailbox_email} appears in both To and Cc. Sender: {sender_email}")
                return True
            
            # 6. Verificar si es respuesta a un ticket existente desde dominio interno
            if self._is_internal_domain_reply(email_content, sender_email):
                logger.warning(f"[LOOP DETECTION] 🔄 Internal domain reply detected from: {sender_email}")
                return True
                
            logger.info(f"[LOOP DETECTION] ✅ Email appears to be external/legitimate from: {sender_email}")
            return False
            
        except Exception as e:
            logger.error(f"Error checking mailbox reply loop: {e}")
            return False

    async def _is_sender_internal_agent(self, sender_email: str, mailbox_email: str) -> bool:
        """
        Verifica si el sender del email es un agente interno del workspace
        """
        try:
            if not sender_email:
                return False
                
            sender_email_lower = sender_email.lower()
            
            # 1. Obtener el workspace_id del mailbox para buscar agentes
            from app.models.microsoft import MailboxConnection
            from app.models.agent import Agent

            mailbox_stmt = select(MailboxConnection).filter(
                MailboxConnection.email.ilike(mailbox_email),
                MailboxConnection.is_active == True
            )
            mailbox_result = await self.db.execute(mailbox_stmt)
            mailbox = mailbox_result.scalar_one_or_none()

            if not mailbox:
                logger.warning(f"[AGENT CHECK] Could not find active mailbox: {mailbox_email}")
                return False

            # 2. Buscar si el sender es un agente en el workspace
            agent_stmt = select(Agent).filter(
                Agent.email.ilike(sender_email),
                Agent.workspace_id == mailbox.workspace_id,
                Agent.is_active == True
            )
            agent_result = await self.db.execute(agent_stmt)
            agent = agent_result.scalar_one_or_none()

            if agent:
                logger.info(f"[AGENT CHECK] ✅ Sender {sender_email} is internal agent: {agent.name}")
                return True

            logger.info(f"[AGENT CHECK] ❌ Sender {sender_email} is not an internal agent")
            return False
            
        except Exception as e:
            logger.error(f"Error checking if sender is internal agent: {e}")
            return False

    def _is_internal_domain_reply(self, email_content: Dict, sender_email: str) -> bool:
        """
        Verifica si es una respuesta desde un dominio interno del sistema
        IMPORTANTE: Solo marca como loop las RESPUESTAS, no los emails de creación de tickets
        """
        try:
            if not sender_email:
                return False
            
            # 1. Verificar si el subject indica que es respuesta a un ticket
            subject = email_content.get("subject", "").lower()
            has_ticket_id = re.search(r'\[id:\d+\]', subject)
            
            if not has_ticket_id:
                # No es respuesta a ticket existente = podría ser nuevo ticket legítimo
                logger.info(f"[INTERNAL DOMAIN] No ticket ID found - allowing as potential new ticket")
                return False  
            
            # 2. Si tiene ticket ID, verificar si es respuesta vs forward
            is_reply = subject.startswith("re:") or "reply" in subject
            is_forward = subject.startswith("fwd:") or subject.startswith("fw:") or "forward" in subject
            
            if is_forward:
                # Forwards pueden ser legítimos incluso desde dominios internos
                logger.info(f"[INTERNAL DOMAIN] Forwarded email detected - allowing")
                return False
            
            # 3. Obtener dominios internos conocidos
            sender_domain = sender_email.split('@')[-1].lower() if '@' in sender_email else ""
            
            # Dominios que sabemos que son internos del sistema
            internal_domains = ["s-fx.com", "enque.cc", "microsoftexchange"]
            
            # 4. Solo marcar como loop si es RESPUESTA desde dominio interno
            if is_reply and any(domain in sender_domain for domain in internal_domains):
                logger.info(f"[INTERNAL DOMAIN] Internal reply to existing ticket from {sender_domain} - likely loop")
                return True
                
            logger.info(f"[INTERNAL DOMAIN] Email from {sender_domain} appears legitimate")
            return False
            
        except Exception as e:
            logger.error(f"Error checking internal domain reply: {e}")
            return False

    async def _determine_primary_contact_for_reply(self, email: EmailData, mailbox_email: str, workspace_id: int) -> Optional['User']:
        """
        Determina el contacto primario correcto para un reply, priorizando usuarios reales sobre mailboxes

        Cuando un reply tiene múltiples destinatarios TO (ej: usuario + mailbox),
        debemos priorizar al usuario real como primary contact, no al mailbox.
        """
        from app.models.user import User

        # 1. Verificar si el sender es el usuario real (caso más común)
        sender_email = email.sender.address.lower()

        # 2. Obtener todos los destinatarios TO para analizar
        to_recipients_emails = [r.address.lower() for r in email.to_recipients if r.address]

        logger.info(f"[REPLY CONTACT] Analyzing reply from: {sender_email}")
        logger.info(f"[REPLY CONTACT] TO recipients: {to_recipients_emails}")

        # 3. Obtener mailboxes activos del workspace para identificarlos
        mailbox_emails = set()
        try:
            from app.models.microsoft import MailboxConnection
            mailboxes_stmt = select(MailboxConnection).filter(
                MailboxConnection.workspace_id == workspace_id,
                MailboxConnection.is_active == True
            )
            mailboxes_result = await self.db.execute(mailboxes_stmt)
            mailboxes = mailboxes_result.scalars().all()
            mailbox_emails = {mb.email.lower() for mb in mailboxes if mb.email}
            logger.info(f"[REPLY CONTACT] Known mailboxes: {mailbox_emails}")
        except Exception as e:
            logger.warning(f"[REPLY CONTACT] Could not get mailbox emails: {e}")

        # 4. Si el sender NO es un mailbox, usar el sender como primary contact
        if sender_email not in mailbox_emails:
            logger.info(f"[REPLY CONTACT] Sender {sender_email} is not a mailbox - using as primary contact")
            return await get_or_create_user(self.db, email.sender.address, email.sender.name or "Unknown", workspace_id=workspace_id)

        # 5. Si el sender ES un mailbox, buscar en los TO recipients un usuario real
        logger.info(f"[REPLY CONTACT] Sender {sender_email} is a mailbox - looking for real user in TO recipients")

        for to_recipient in email.to_recipients:
            to_email = to_recipient.address.lower()

            # Skip si es un mailbox conocido
            if to_email in mailbox_emails:
                logger.info(f"[REPLY CONTACT] Skipping mailbox in TO: {to_email}")
                continue

            # Skip si es el mismo mailbox que está enviando
            if to_email == mailbox_email.lower():
                logger.info(f"[REPLY CONTACT] Skipping same mailbox: {to_email}")
                continue

            # Este debería ser el usuario real
            logger.info(f"[REPLY CONTACT] Found real user in TO recipients: {to_email} - using as primary contact")
            return await get_or_create_user(self.db, to_recipient.address, to_recipient.name or "Unknown", workspace_id=workspace_id)

        # 6. Fallback: usar el sender original si no encontramos nada mejor
        logger.warning(f"[REPLY CONTACT] Could not find real user, falling back to sender: {sender_email}")
        return await get_or_create_user(self.db, email.sender.address, email.sender.name or "Unknown", workspace_id=workspace_id)

    async def sync_emails(self, sync_config: EmailSyncConfig, get_user_email_for_sync_func):
        user_email, token = await get_user_email_for_sync_func(sync_config) # This calls the sync check_and_refresh_all_tokens
        if not user_email or not token:
            logger.warning(f"[MAIL SYNC] No valid email or token found for sync config ID: {sync_config.id}. Skipping sync.")
            return []
        try:
            user_access_token = token.access_token
            emails = self.graph_client.get_mailbox_emails(user_access_token, user_email, sync_config.folder_name, top=50, filter_unread=True)
            
            if not emails:
                sync_config.last_sync_time = datetime.utcnow()
                await self.db.commit()
                return []
            created_tasks_count = 0; added_comments_count = 0
            processed_folder_id = self.graph_client.get_or_create_processed_folder(user_access_token, user_email, "Enque Processed")
            if not processed_folder_id: 
                logger.error(f"[MAIL SYNC] Could not get or create 'Enque Processed' folder for {user_email}. Emails will not be moved.")
            else:
                pass  
            system_agent_result = await self.db.execute(
                select(Agent).filter(Agent.email == "system@enque.cc")
            )
            system_agent = system_agent_result.scalar_one_or_none()
            
            if not system_agent:
                all_agents_result = await self.db.execute(
                    select(Agent).order_by(Agent.id.asc()).limit(1)
                )
                system_agent = all_agents_result.scalar_one_or_none()
            if not system_agent: logger.error("No system agent found. Cannot process emails."); return []
            
            notification_subject_patterns = [
                "New ticket #", 
                "Ticket #",
                "New response to your ticket #",
                "Enque 🎟️",  
                "[ID:",      
                "has been assigned"
            ]


            system_domains = await self._get_system_domains_for_workspace(sync_config.workspace_id)
            
            for email_data in emails:
                email_id = email_data.get("id")
                email_subject = email_data.get("subject", "")
                sender_email = email_data.get("from", {}).get("emailAddress", {}).get("address", "")
                
                if not email_id: logger.warning("[MAIL SYNC] Skipping email with missing ID."); continue
                try:
                    existing_mapping_result = await self.db.execute(
                        select(EmailTicketMapping).filter(EmailTicketMapping.email_id == email_id)
                    )
                    existing_mapping = existing_mapping_result.scalar_one_or_none()
                    if existing_mapping:
                        ticket_exists_result = await self.db.execute(
                            select(Task).filter(Task.id == existing_mapping.ticket_id)
                        )
                        ticket_exists = ticket_exists_result.scalar_one_or_none()
                        if not ticket_exists:
                            logger.warning(f"🚨 ORPHANED MAPPING: Email {email_id} maps to non-existent ticket #{existing_mapping.ticket_id}. Cleaning up...")
                            await self.db.delete(existing_mapping)
                            await self.db.commit()
                            logger.info(f"✅ Cleaned orphaned mapping for email {email_id}")
                        else:
                            mapping_subject = existing_mapping.email_subject or ""
                            current_subject = email_subject or ""
                            
                            if mapping_subject and current_subject and mapping_subject.lower() != current_subject.lower():
                                logger.warning(f"🚨 INCONSISTENT MAPPING: Email {email_id} mapped to ticket #{existing_mapping.ticket_id}")
                                logger.warning(f"   Removing inconsistent mapping...")
                                await self.db.delete(existing_mapping)
                                await self.db.commit()
                                logger.info(f"✅ Cleaned inconsistent mapping for email {email_id}")
                                # Continue processing as if it's a new email
                            else:
                                continue
                    
                    email_content = self.graph_client.get_mailbox_email_content(user_access_token, user_email, email_id)
                    if not email_content: logger.warning(f"[MAIL SYNC] Could not retrieve full content for email ID {email_id}. Skipping."); continue
                    
                    # 🔧 ANTI-LOOP: Verificar si el mailbox está procesando su propia respuesta
                    if await self._is_mailbox_reply_loop(email_content, user_email):
                        logger.info(f"[MAIL SYNC] 🔄 Skipping internal reply loop for email {email_id}: {email_subject}")
                        # Marcar como leído y mover a procesados para evitar reprocesamiento
                        self.graph_client.mark_email_as_read(user_access_token, user_email, email_id)
                        if processed_folder_id:
                            self.graph_client.move_email_to_folder(user_access_token, user_email, email_id, processed_folder_id)
                        continue
                    
                    conversation_id = email_content.get("conversationId")
                    
                    existing_mapping_by_conv = None
                    if conversation_id:
                        existing_mapping_by_conv_result = await self.db.execute(
                            select(EmailTicketMapping)
                            .filter(EmailTicketMapping.email_conversation_id == conversation_id)
                            .order_by(EmailTicketMapping.created_at.asc())
                        )
                        existing_mapping_by_conv = existing_mapping_by_conv_result.scalars().first()
                    
                    if not existing_mapping_by_conv and email_subject:
                        id_match = re.search(r'\[ID:(\d+)\]', email_subject, re.IGNORECASE)
                        if id_match:
                            ticket_id_from_subject = int(id_match.group(1))
                            existing_mapping_by_subject_result = await self.db.execute(
                                select(EmailTicketMapping)
                                .filter(EmailTicketMapping.ticket_id == ticket_id_from_subject)
                                .order_by(EmailTicketMapping.created_at.asc())
                            )
                            existing_mapping_by_conv = existing_mapping_by_subject_result.scalars().first()
                            if existing_mapping_by_conv:
                                logger.info(f"[MAIL SYNC] Found existing ticket {ticket_id_from_subject} by subject ID for email {email_id}")
                        
                    if existing_mapping_by_conv:
                        email = await self._parse_email_data(email_content, user_email, sync_config.workspace_id)
                        if not email: logger.warning(f"[MAIL SYNC] Could not parse reply email data for email ID {email_id}. Skipping comment creation."); continue
                        
                        # 🔧 MEJORA: Determinar el usuario correcto para el reply
                        # Si hay múltiples destinatarios TO, priorizar usuario real sobre mailbox
                        reply_user = await self._determine_primary_contact_for_reply(email, user_email, sync_config.workspace_id)

                        if not reply_user: logger.error(f"Could not determine primary contact for reply email: {email_id}"); continue
                        workspace_result = await self.db.execute(
                            select(Workspace).filter(Workspace.id == sync_config.workspace_id)
                        )
                        workspace = workspace_result.scalar_one_or_none()
                        if not workspace: logger.error(f"Workspace ID {sync_config.workspace_id} not found for reply. Skipping comment creation."); continue
                        processed_reply_html = self._process_html_body(email.body_content, email.attachments, f"reply email {email.id}")
                        
                        processed_reply_html = re.sub(r'^<p><strong>From:</strong>.*?</p>', '', processed_reply_html, flags=re.DOTALL | re.IGNORECASE)
                        
                        special_metadata = f'<original-sender>{reply_user.name}|{reply_user.email}</original-sender>'
                        
                        content_to_store = special_metadata + processed_reply_html
                        s3_html_url = None
                        
                        try:
                            if content_to_store and content_to_store.strip():
                                from app.services.s3_service import get_s3_service
                                s3_service = get_s3_service()
                                
                                content_length = len(content_to_store)
                                should_migrate_to_s3 = (
                                    content_length > 65000 or 
                                    s3_service.should_store_html_in_s3(content_to_store)
                                )
                                
                                if should_migrate_to_s3:
                                    import uuid
                                    temp_id = str(uuid.uuid4())
                                    
                                    s3_url = s3_service.upload_html_content(
                                        html_content=content_to_store,
                                        filename=f"temp-comment-{temp_id}.html",
                                        folder="comments"
                                    )
                                    
                                    s3_html_url = s3_url
                                    content_to_store = f"[MIGRATED_TO_S3] Content moved to S3: {s3_url}"
                        except Exception as e:
                            logger.error(f"❌ [MAIL SYNC] Error pre-migrating content to S3: {str(e)}")
                            content_to_store = special_metadata + processed_reply_html
                            s3_html_url = None

                        new_comment = Comment(
                            ticket_id=existing_mapping_by_conv.ticket_id,
                            agent_id=system_agent.id,
                            workspace_id=workspace.id,
                            content=content_to_store,  
                            s3_html_url=s3_html_url,  
                            is_private=False
                        )

                        if email.attachments:
                            non_inline_attachments = [att for att in email.attachments if not att.is_inline and att.contentBytes]
                            if non_inline_attachments:
                                for att in non_inline_attachments:
                                    try:
                                        decoded_bytes = base64.b64decode(att.contentBytes)
                                        
                                        s3_url = None
                                        try:
                                            from app.services.s3_service import get_s3_service
                                            s3_service = get_s3_service()
                                            
                                            folder = "images" if att.content_type.startswith("image/") else "documents"
                                            
                                            s3_url = s3_service.upload_file(
                                                file_content=decoded_bytes,
                                                filename=att.name,
                                                content_type=att.content_type,
                                                folder=folder
                                            )
                                            
                                            logger.info(f"📎 Adjunto '{att.name}' subido a S3: {s3_url}")
                                            
                                        except Exception as s3_error:
                                            logger.error(f"❌ Error subiendo adjunto '{att.name}' a S3: {str(s3_error)}")
                                            pass
                                        
                                        db_attachment = TicketAttachment(
                                            file_name=att.name,
                                            content_type=att.content_type,
                                            file_size=att.size,
                                            s3_url=s3_url,  
                                            content_bytes=decoded_bytes if not s3_url else None  # Solo bytes si S3 falló
                                        )
                                        new_comment.attachments.append(db_attachment) # SQLAlchemy manejará el comment_id
                                        
                                    except Exception as e:
                                        logger.error(f"Error al procesar/decodificar adjunto '{att.name}' para comentario en ticket {existing_mapping_by_conv.ticket_id}: {e}", exc_info=True)
                        
                        self.db.add(new_comment)

                        if s3_html_url and not s3_html_url.endswith(f"comment-{new_comment.id}.html"):
                            try:
                                await self.db.flush()
                                
                                from app.services.s3_service import get_s3_service
                                s3_service = get_s3_service()
                                
                                original_content = special_metadata + processed_reply_html
                                
                                final_s3_url = s3_service.store_comment_html(new_comment.id, original_content)
                                
                                new_comment.s3_html_url = final_s3_url
                                new_comment.content = f"[MIGRATED_TO_S3] Content moved to S3: {final_s3_url}"
                            except Exception as e:
                                logger.warning(f"⚠️ [MAIL SYNC] Could not rename S3 file for comment {new_comment.id}: {str(e)}")

                        ticket_to_update_result = await self.db.execute(
                            select(Task).filter(Task.id == existing_mapping_by_conv.ticket_id)
                        )
                        ticket_to_update = ticket_to_update_result.scalar_one_or_none()
                        
                        try:
                            from app.services.workflow_service import WorkflowService
                            
                            if email.body_content and email.body_content.strip():
                                workflow_service = WorkflowService(self.db)
                                
                                workflow_context = {
                                    'task_id': existing_mapping_by_conv.ticket_id,
                                    'comment_id': None,  
                                    'agent_id': system_agent.id,  
                                    'workspace_id': workspace.id,
                                    'task_status': ticket_to_update.status if ticket_to_update else 'unknown',
                                    'task_priority': getattr(ticket_to_update, 'priority', 'normal') if ticket_to_update else 'normal',
                                    'is_private': False,
                                    'is_from_email': True,
                                    'email_sender': reply_user.email,
                                    'email_sender_name': reply_user.name
                                }

                                workflow_results = await workflow_service.process_message_for_workflows(
                                    email.body_content,
                                    workspace.id,
                                    workflow_context
                                )
                                
                                if workflow_results:
                                    logger.info(f"[MAIL SYNC] Executed {len(workflow_results)} workflows for email reply on ticket {existing_mapping_by_conv.ticket_id}")
                                    for result in workflow_results:
                                        logger.info(f"[MAIL SYNC] Workflow executed: {result.get('workflow_name')} - {result.get('trigger')}")
                                
                        except Exception as workflow_error:
                            logger.error(f"[MAIL SYNC] Error processing workflows for email reply: {str(workflow_error)}")
                        
                        user_activity = Activity(
                            agent_id=None,  
                            action=f"{reply_user.name} commented on ticket",  
                            source_type="Comment",
                            source_id=existing_mapping_by_conv.ticket_id,  
                            workspace_id=workspace.id
                        )
                        self.db.add(user_activity)
                        
                        reply_email_mapping = EmailTicketMapping(
                            email_id=email.id, email_conversation_id=email.conversation_id, ticket_id=existing_mapping_by_conv.ticket_id,
                            email_subject=email.subject, email_sender=f"{email.sender.name} <{email.sender.address}>",
                            email_received_at=email.received_at, is_processed=True)
                        self.db.add(reply_email_mapping)
                        
                        if ticket_to_update and ticket_to_update.status == TaskStatus.WITH_USER:
                             ticket_to_update.status = TaskStatus.IN_PROGRESS; self.db.add(ticket_to_update)
                             logger.info(f"[MAIL SYNC] Ticket {existing_mapping_by_conv.ticket_id} status changed from WITH_USER to IN_PROGRESS after user reply")
                        elif ticket_to_update and ticket_to_update.status == TaskStatus.CLOSED:
                             ticket_to_update.status = TaskStatus.IN_PROGRESS; self.db.add(ticket_to_update)
                             logger.info(f"[MAIL SYNC] Ticket {existing_mapping_by_conv.ticket_id} status changed from CLOSED to IN_PROGRESS after user reply")
                        elif ticket_to_update: pass  
                        else: logger.warning(f"[MAIL SYNC] Could not find Ticket ID {existing_mapping_by_conv.ticket_id} to potentially update status after user reply.")
                        if ticket_to_update:
                            ticket_to_update.last_update = datetime.utcnow()
                            self.db.add(ticket_to_update)
                            logger.info(f"[MAIL SYNC] Updated last_update for ticket {existing_mapping_by_conv.ticket_id} after user reply")
                        
                        await self.db.commit()
                        added_comments_count += 1

                        comment_with_attachments = None
                        try:
                            # Refresh comment with attachments loaded to avoid lazy loading issues
                            comment_with_attachments_result = await self.db.execute(
                                select(Comment).options(joinedload(Comment.attachments))
                                .filter(Comment.id == new_comment.id)
                            )
                            comment_with_attachments = comment_with_attachments_result.unique().scalar_one_or_none()

                            if not comment_with_attachments:
                                logger.warning(f"[MAIL SYNC] Could not reload comment {new_comment.id} for Socket.IO event")
                                comment_with_attachments = new_comment

                            full_content = ""
                            if comment_with_attachments.s3_html_url:
                                full_content = special_metadata + processed_reply_html
                            else:
                                full_content = comment_with_attachments.content or ""
                            attachments_data = []
                            for attachment in (comment_with_attachments.attachments if hasattr(comment_with_attachments, 'attachments') else []):
                                attachments_data.append({
                                    'id': attachment.id,
                                    'file_name': attachment.file_name,
                                    'content_type': attachment.content_type,
                                    'file_size': attachment.file_size,
                                    'download_url': attachment.s3_url  
                                })
                            
                            comment_data = {
                                'id': comment_with_attachments.id,
                                'ticket_id': existing_mapping_by_conv.ticket_id,
                                'agent_id': None,
                                'user_id': reply_user.id,
                                'user_name': reply_user.name,
                                'content': full_content,
                                'is_private': False,
                                'created_at': comment_with_attachments.created_at.isoformat() if comment_with_attachments.created_at else None,
                                'attachments': attachments_data
                            }
                            from app.core.socketio import emit_comment_update_sync
                            emit_comment_update_sync(
                                workspace_id=workspace.id,
                                comment_data=comment_data
                            )
                            
                            logger.info(f"📤 [MAIL SYNC] Socket.IO comment_updated event queued for workspace {workspace.id}")
                        except Exception as e:
                            logger.error(f"❌ [MAIL SYNC] Error emitting Socket.IO event for comment {comment_with_attachments.id if comment_with_attachments else new_comment.id}: {str(e)}")
                        
                        if processed_folder_id: 
                            new_reply_id = self.graph_client.move_email_to_folder(user_access_token, user_email, email_id, processed_folder_id)
                            if new_reply_id and new_reply_id != email_id:
                                logger.info(f"📧 Reply email moved - ID changed from {email_id[:50]}... to {new_reply_id[:50]}...")
                                await self._update_all_email_mappings_for_ticket(existing_mapping_by_conv.ticket_id, email_id, new_reply_id)
                        continue
                    else:
                        
                        email_subject_lower = email_subject.lower()
                        
                        is_system_notification = False
                        
                        sender_email_lower = sender_email.lower()
                        mailbox_email = user_email.lower()

                        if any(domain in sender_email_lower for domain in system_domains) or sender_email_lower == mailbox_email:
                            for pattern in notification_subject_patterns:
                                if pattern.lower() in email_subject_lower:
                                    is_system_notification = True
                                    
                                    self.graph_client.mark_email_as_read(user_access_token, user_email, email_id)
                                    if processed_folder_id:
                                        self.graph_client.move_email_to_folder(user_access_token, user_email, email_id, processed_folder_id)
                                    break
                        
                        if is_system_notification:
                            logger.info(f"[MAIL SYNC] Skipping system notification email: {email_subject}")
                            continue
                        
                        logger.info(f"[MAIL SYNC] Email ID {email_id} is a new conversation. Creating new ticket.")
                        email = await self._parse_email_data(email_content, user_email, sync_config.workspace_id)
                        if not email: 
                            logger.warning(f"[MAIL SYNC] Could not parse new email data for email ID {email_id}. Skipping ticket creation.")
                            continue
                        
                        sender_email = email.sender.address if email.sender else ""
                        if sender_email.lower() == user_email.lower() or "microsoftexchange" in sender_email.lower():
                            logger.warning(f"[MAIL SYNC] Email from system address or self ({sender_email}). Marking as read and skipping ticket creation.")
                            self.graph_client.mark_email_as_read(user_access_token, user_email, email_id)
                            if processed_folder_id:
                                self.graph_client.move_email_to_folder(user_access_token, user_email, email_id, processed_folder_id)
                            continue

                        task = await self._create_task_from_email(email, sync_config, system_agent)
                        if task:
                            created_tasks_count += 1; logger.info(f"[MAIL SYNC] Created Task ID {task.id} from Email ID {email.id}.")
                            email_mapping = EmailTicketMapping(
                                email_id=email.id, email_conversation_id=email.conversation_id, ticket_id=task.id,
                                email_subject=email.subject, email_sender=f"{email.sender.name} <{email.sender.address}>",
                                email_received_at=email.received_at, is_processed=True)
                            self.db.add(email_mapping)
                            try:
                                await self.db.commit()
                                if processed_folder_id:
                                    new_id = self.graph_client.move_email_to_folder(user_access_token, user_email, email_id, processed_folder_id)
                                    if new_id and new_id != email_id:
                                        # 🔧 MEJORADO: Email ID changed after move, updating ALL related mappings
                                        logger.info(f"📧 Email moved - ID changed from {email_id[:50]}... to {new_id[:50]}...")
                                        await self._update_all_email_mappings_for_ticket(task.id, email_id, new_id)
                            except Exception as commit_err:
                                logger.error(f"[MAIL SYNC] Error committing email mapping for task {task.id}: {str(commit_err)}")
                                await self.db.rollback()
                        else: logger.warning(f"[MAIL SYNC] Failed to create task from email ID {email.id}.")
                except (DatabaseException, MicrosoftAPIException) as e:
                    logger.error(
                        f"[MAIL SYNC] Error processing email ID {email_data.get('id', 'N/A')}: {e}",
                        extra={
                            "email_id": email_data.get("id"),
                            "subject": email_data.get("subject"),
                            "sync_config_id": sync_config.id,
                            "workspace_id": sync_config.workspace_id,
                            "error_type": type(e).__name__
                        },
                        exc_info=True
                    )
                except Exception as e:
                    logger.error(
                        f"[MAIL SYNC] An unexpected error occurred while processing email ID {email_data.get('id', 'N/A')}: {e}",
                        extra={
                            "email_id": email_data.get("id"),
                            "subject": email_data.get("subject"),
                            "sync_config_id": sync_config.id,
                            "workspace_id": sync_config.workspace_id,
                            "error_type": type(e).__name__
                        },
                        exc_info=True
                    )
                    
                    # Manejo mejorado de errores de sesión
                    try:
                        self.db.rollback()
                        logger.info(f"[MAIL SYNC] Successfully rolled back transaction after error")
                    except Exception as rollback_error:
                        logger.error(f"[MAIL SYNC] Error during rollback: {str(rollback_error)}")
                        # Si el rollback falla, crear nueva sesión
                        try:
                            self.db.close()
                            from app.database.session import SessionLocal
                            self.db = SessionLocal()
                            logger.info(f"[MAIL SYNC] Created new database session after failed rollback")
                        except Exception as session_error:
                            logger.error(f"[MAIL SYNC] Error creating new session: {str(session_error)}")
                    
                    continue
            sync_config.last_sync_time = datetime.utcnow()
            await self.db.commit()
            if sync_config.id % 10 == 0:
                self._cleanup_orphaned_mappings()
            
            if created_tasks_count > 0 or added_comments_count > 0:
                logger.info(f"📧 Config {sync_config.id}: {created_tasks_count} tickets, {added_comments_count} comments")
            return []
        except (DatabaseException, MicrosoftAPIException) as e:
            logger.error(
                f"[MAIL SYNC] Error during email synchronization for config ID {sync_config.id}: {e}",
                extra={
                    "sync_config_id": sync_config.id,
                    "workspace_id": sync_config.workspace_id,
                    "mailbox_connection_id": sync_config.mailbox_connection_id,
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            return []
        except Exception as e:
            logger.error(
                f"[MAIL SYNC] An unexpected error occurred during email synchronization for config ID {sync_config.id}: {e}",
                extra={
                    "sync_config_id": sync_config.id,
                    "workspace_id": sync_config.workspace_id,
                    "mailbox_connection_id": sync_config.mailbox_connection_id,
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            return []

    def _cleanup_orphaned_mappings(self):
        try:
            orphaned_mappings = self.db.query(EmailTicketMapping).filter(
                ~EmailTicketMapping.ticket_id.in_(
                    self.db.query(Task.id).filter(Task.is_deleted == False)
                )
            ).all()
            inconsistent_mappings = []
            recent_mappings = self.db.query(EmailTicketMapping).filter(
                EmailTicketMapping.created_at > datetime.utcnow() - timedelta(hours=24)
            ).limit(100).all() 
            
            for mapping in recent_mappings:
                if mapping.email_subject:
                    ticket = self.db.query(Task).filter(Task.id == mapping.ticket_id).first()
                    if ticket and ticket.title:
                        if (mapping.email_subject.lower() != ticket.title.lower() and 
                            not any(word in ticket.title.lower() for word in mapping.email_subject.lower().split()[:3])):
                            inconsistent_mappings.append(mapping)
            
            total_cleaned = 0
            
            if orphaned_mappings:
                logger.warning(f"🧹 Found {len(orphaned_mappings)} orphaned email mappings. Cleaning up...")
                for mapping in orphaned_mappings:
                    self.db.delete(mapping)
                total_cleaned += len(orphaned_mappings)
            
            if inconsistent_mappings:
                logger.warning(f"🧹 Found {len(inconsistent_mappings)} inconsistent email mappings. Cleaning up...")
                for mapping in inconsistent_mappings:
                    self.db.delete(mapping)
                total_cleaned += len(inconsistent_mappings)
            
            if total_cleaned > 0:
                self.db.commit()
                logger.info(f"✅ Cleaned up {total_cleaned} problematic email mappings ({len(orphaned_mappings)} orphaned, {len(inconsistent_mappings)} inconsistent)")
            # No problematic mappings found
                
        except Exception as e:
            logger.error(f"❌ Error during mappings cleanup: {str(e)}")
            self.db.rollback()

    def _extract_original_sender_from_forwarded_email(self, email_content: str, subject: str = "") -> tuple[Optional[str], Optional[str]]:
        if not email_content:
            return None, None

        # 🔒 FIX: Decode HTML entities FIRST (convert &lt; to <, &gt; to >, etc.)
        from html import unescape
        decoded_content = unescape(email_content)

        forwarded_patterns = [
            r"---------- Forwarded message ---------",
            r"Begin forwarded message:",
            r"-----Original Message-----",
            r"-----Mensaje original-----",
            r"From:.*?<br>",
            r"De:.*?<br>",
            r"Subject.*?FW:|Subject.*?Fwd:",
            r"Asunto.*?RV:|Asunto.*?Reenviado:"
        ]
        is_forwarded = any(re.search(pattern, decoded_content, re.IGNORECASE | re.DOTALL)
                          for pattern in forwarded_patterns)
        if subject:
            subject_forwarded_patterns = [r"^FW:", r"^Fwd:", r"^RV:", r"^Reenviado:"]
            is_forwarded = is_forwarded or any(re.search(pattern, subject, re.IGNORECASE)
                                             for pattern in subject_forwarded_patterns)

        if not is_forwarded:
            return None, None

        logger.info(f"[FORWARD DETECTION] Email detected as forwarded. Extracting original sender...")

        # 🔒 FIX: Enhanced patterns to handle HTML and plain text formats
        original_sender_patterns = [
            # HTML formats with <b> tags and <span>
            r"<b>\s*From:\s*</b>\s*<span[^>]*>\s*(.*?)\s*<(.*?)>\s*<",
            r"<b>\s*From:\s*</b>\s*(.*?)\s*<(.*?)>",
            r"<b>\s*De:\s*</b>\s*<span[^>]*>\s*(.*?)\s*<(.*?)>\s*<",
            r"<b>\s*De:\s*</b>\s*(.*?)\s*<(.*?)>",

            # Plain text with mailto
            r"From:\s*\"?(.*?)\"?\s*\[mailto:(.*?)\]",
            r"De:\s*\"?(.*?)\"?\s*\[mailto:(.*?)\]",

            # Standard email format: Name <email@domain.com>
            r"From:\s*(.*?)\s*<(.*?)>",
            r"De:\s*(.*?)\s*<(.*?)>",
            r"From:\s*([^<\n]+)\s*<([^>\n]+)>",
            r"De:\s*([^<\n]+)\s*<([^>\n]+)>",

            # Email only (no name)
            r"From:\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
            r"De:\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"
        ]

        for pattern in original_sender_patterns:
            match = re.search(pattern, decoded_content, re.IGNORECASE | re.DOTALL)
            if match:
                if len(match.groups()) == 2:
                    # Patrón con nombre y email
                    name = match.group(1).strip().strip('"').strip("'")
                    email = match.group(2).strip()

                    # Clean up HTML tags from name if present
                    name = re.sub(r'<[^>]+>', '', name).strip()
                elif len(match.groups()) == 1:
                    # Solo email
                    email = match.group(1).strip()
                    name = email.split('@')[0]  # Usar la parte antes del @ como nombre
                else:
                    continue

                # Validar que el email sea válido
                if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
                    logger.info(f"[FORWARD DETECTION] ✅ Original sender found: {name} <{email}>")
                    return email, name

        # 🔒 FIX: Improved fallback - decode before searching
        email_pattern = r'\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b'
        emails_in_content = re.findall(email_pattern, decoded_content)

        # Filter out known system domains that shouldn't be primary contact
        system_domains = ['cmtassociation.org', 's-fx.com', 'enque.cc']
        filtered_emails = [
            email for email in emails_in_content
            if not any(domain in email.lower() for domain in system_domains)
        ]

        if filtered_emails:
            first_email = filtered_emails[0]
            logger.info(f"[FORWARD DETECTION] Fallback: Using first external email: {first_email}")
            return first_email, first_email.split('@')[0]
        elif emails_in_content:
            first_email = emails_in_content[0]
            logger.info(f"[FORWARD DETECTION] Fallback: Using first email found: {first_email}")
            return first_email, first_email.split('@')[0]

        logger.warning(f"[FORWARD DETECTION] Could not extract original sender from forwarded email")
        return None, None

    def _extract_recipients_from_body(self, email_body: str, header: str) -> List[str]:
        """
        Extract recipient emails from forwarded email body.
        Supports multiple recipients separated by semicolons or commas.
        """
        if not email_body or not header:
            return []

        # 🔒 FIX: Decode HTML entities before extracting recipients
        from html import unescape
        decoded_body = unescape(email_body)

        # Try multiple patterns for different email client formats
        patterns = [
            re.compile(rf"<b>{header}:</b>\s*(.*?)\s*<br>", re.IGNORECASE),
            re.compile(rf"<strong>{header}:</strong>\s*(.*?)\s*<br>", re.IGNORECASE),
            re.compile(rf"<font[^>]*><b>{header}:</b>(.*?)</font>", re.IGNORECASE | re.DOTALL),
        ]

        recipients_str = None
        for pattern in patterns:
            match = pattern.search(decoded_body)
            if match:
                recipients_str = match.group(1)
                break

        if not recipients_str:
            return []

        # Extract all email addresses from the matched string
        # This handles multiple recipients separated by ; or ,
        email_pattern = re.compile(r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b')
        emails = email_pattern.findall(recipients_str)

        logger.info(f"[FORWARD EXTRACTION] Found {len(emails)} {header} recipient(s): {emails}")
        return emails

    def _clean_email_address(self, email_string: str) -> Optional[str]:
        if not email_string:
            return None      
        import re
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        match = re.search(email_pattern, email_string)
        
        if match:
            return match.group(0)
        cleaned = email_string.strip()
        if '@' in cleaned:
            parts = cleaned.split('@')
            if len(parts) == 2:
                local_part = parts[0].strip().split()[-1]  
                domain_part = parts[1].strip().split()[0]  
                return f"{local_part}@{domain_part}"
        
        return None

    async def _parse_email_data(self, email_content: Dict, user_email: str, workspace_id: int = None) -> Optional[EmailData]:
        try:
            sender_data = email_content.get("from", {}).get("emailAddress", {})
            sender_address = self._clean_email_address(sender_data.get("address", ""))
            if not sender_address: 
                logger.warning(f"Could not parse sender from email content: {email_content.get('id')}")
                return None
            sender = EmailAddress(name=sender_data.get("name", ""), address=sender_address)
            sender_email = sender.address.lower()
            if workspace_id:
                system_domains = await self._get_system_domains_for_workspace(workspace_id)
            else:
                system_domains = ["enque.cc", "microsoftexchange"]  # Fallback básico
                
            notification_subjects = ["new ticket #", "ticket #", "new response", "[id:"]
            if sender_email == user_email.lower() or any(domain in sender_email for domain in system_domains):
                logger.warning(f"Email from system address or company domain: {sender_email}")
                # No rechazar completamente, pero marcar para que luego se pueda filtrar
                
            # Si el asunto parece ser una notificación del sistema
            if email_content.get("subject", ""):
                subject_lower = email_content.get("subject", "").lower()
                if any(phrase in subject_lower for phrase in notification_subjects):
                    logger.warning(f"Email subject appears to be a system notification: {email_content.get('subject')}")
            recipients = []
            for r in email_content.get("toRecipients", []):
                if r.get("emailAddress"):
                    cleaned_address = self._clean_email_address(r.get("emailAddress", {}).get("address", ""))
                    if cleaned_address:
                        recipients.append(EmailAddress(name=r.get("emailAddress", {}).get("name", ""), address=cleaned_address))
            if not recipients: recipients = [EmailAddress(name="", address=user_email)]
            cc_recipients = []
            for r in email_content.get("ccRecipients", []):
                if r.get("emailAddress"):
                    cleaned_address = self._clean_email_address(r.get("emailAddress", {}).get("address", ""))
                    if cleaned_address:
                        cc_recipients.append(EmailAddress(name=r.get("emailAddress", {}).get("name", ""), address=cleaned_address))
            bcc_recipients = []
            for r in email_content.get("bccRecipients", []):
                if r.get("emailAddress"):
                    cleaned_address = self._clean_email_address(r.get("emailAddress", {}).get("address", ""))
                    if cleaned_address:
                        bcc_recipients.append(EmailAddress(name=r.get("emailAddress", {}).get("name", ""), address=cleaned_address))
            
            body_data = email_content.get("body", {}); body_content = body_data.get("content", ""); body_type = body_data.get("contentType", "html")
            received_time = datetime.utcnow(); received_dt_str = email_content.get("receivedDateTime")
            if received_dt_str:
                try: received_time = datetime.fromisoformat(received_dt_str.replace('Z', '+00:00'))
                except Exception as date_parse_error: logger.warning(f"Could not parse receivedDateTime '{received_dt_str}': {date_parse_error}")
            attachments = []
            for i, att_data in enumerate(email_content.get("attachments", [])):
                try:
                    attachments.append(EmailAttachment(
                        id=att_data["id"], name=att_data["name"], content_type=att_data["contentType"],
                        size=att_data.get("size", 0), is_inline=att_data.get("isInline", False),
                        contentId=att_data.get("contentId"), contentBytes=att_data.get("contentBytes")))
                except KeyError as ke: logger.error(f"Missing key while parsing attachment {i+1} for email {email_content.get('id')}: {ke}"); continue
                except Exception as att_err: logger.error(f"Error parsing attachment {i+1} for email {email_content.get('id')}: {att_err}"); continue
            internet_message_id = email_content.get("internetMessageId")
            
            return EmailData(
                id=email_content["id"], internet_message_id=internet_message_id, conversation_id=email_content.get("conversationId", ""), subject=email_content.get("subject", "No Subject"),
                sender=sender, to_recipients=recipients, cc_recipients=cc_recipients, bcc_recipients=bcc_recipients,
                body_content=body_content, body_type=body_type, received_at=received_time,
                attachments=attachments, importance=email_content.get("importance", "normal"))
        except Exception as e: logger.error(f"Error parsing email data for email ID {email_content.get('id', 'N/A')}: {str(e)}", exc_info=True); return None

    async def _create_task_from_email(self, email: EmailData, config: EmailSyncConfig, system_agent: Agent) -> Optional[Task]:
        if not system_agent: logger.error("System agent is required for _create_task_from_email but was not provided."); return None
        if email.subject:
            subject_lower = email.subject.lower()
            if any(fw_pattern in subject_lower for fw_pattern in ["fw:", "fwd:", "rv:", "reenviado:"]):
                logger.info(f"Permitiendo email con forward en asunto: '{email.subject}'")
            else:
                notification_patterns = [
                    "new ticket #", "ticket #", "new response", 
                    "assigned", "has been created", "notification:",
                    "automated message", "do not reply", "noreply"
                ]
                if any(pattern in subject_lower for pattern in notification_patterns):
                    logger.warning(f"Ignorando correo con asunto '{email.subject}' que parece ser una notificación del sistema")
                    return None
                if "[id:" in subject_lower:
                    sender_domain = email.sender.address.split('@')[-1].lower() if '@' in email.sender.address else ""
                    system_domains = await self._get_system_domains_for_workspace(config.workspace_id)
                    core_system_domains = ["enque.cc", "microsoftexchange"]
                    if sender_domain not in core_system_domains and sender_domain not in system_domains:
                        logger.info(f"Permitiendo respuesta de usuario externo con [ID:] en asunto: {email.sender.address} - '{email.subject}'")
                    else:
                        logger.warning(f"Ignorando correo con [ID:] de dominio del sistema: {email.sender.address} - '{email.subject}'")
                        return None
        sender_domain = email.sender.address.split('@')[-1].lower() if '@' in email.sender.address else ""
        system_domains = await self._get_system_domains_for_workspace(config.workspace_id)
        core_system_domains = ["enque.cc", "microsoftexchange"]
        if sender_domain in core_system_domains:
            logger.warning(f"Ignorando correo del dominio del sistema core: {sender_domain} - {email.sender.address}")
            return None
        workspace_domains = [d for d in system_domains if d not in core_system_domains]
        if sender_domain in workspace_domains and email.subject:
            subject_lower = email.subject.lower()
            if any(keyword in subject_lower for keyword in ["new ticket #", "ticket #", "[id:", "has been"]):
                logger.warning(f"Ignorando notificación de dominio del workspace {sender_domain} con asunto '{email.subject}'")
                return None
            else:
                logger.info(f"Permitiendo email legítimo de dominio del workspace {sender_domain} con asunto '{email.subject}'")
        
        try:
            priority = config.default_priority
            if email.importance == "high": priority = "High"
            elif email.importance == "low": priority = "Low"
            workspace_id = config.workspace_id
            if not workspace_id: logger.error(f"Missing workspace_id in sync config {config.id}. Cannot create user/task."); return None
            original_email, original_name = self._extract_original_sender_from_forwarded_email(
                email.body_content, email.subject
            )

            is_forwarded = bool(original_email)
                    
            if is_forwarded:
                logger.info(f"[FORWARD DETECTION] Creating ticket with original sender: {original_name} <{original_email}>")
                user = await get_or_create_user(self.db, original_email, original_name, workspace_id=workspace_id)
                forwarded_by_email = email.sender.address
                forwarded_by_name = email.sender.name or "Unknown"
                logger.info(f"[FORWARD DETECTION] Email was forwarded by: {forwarded_by_name} <{forwarded_by_email}>")

                original_to = self._extract_recipients_from_body(email.body_content, "To")
                original_cc = self._extract_recipients_from_body(email.body_content, "Cc")

                to_recipients_str = ", ".join(original_to) if original_to else None
                cc_recipients_str = ", ".join(original_cc) if original_cc else None
            else:
                user = await get_or_create_user(self.db, email.sender.address, email.sender.name or "Unknown", workspace_id=workspace_id)

                # 🔒 FIX: Get workspace mailboxes to filter them from recipients
                mailbox_emails = set()
                try:
                    from app.models.microsoft import MailboxConnection
                    mailboxes_stmt = select(MailboxConnection).filter(
                        MailboxConnection.workspace_id == workspace_id,
                        MailboxConnection.is_active == True
                    )
                    mailboxes_result = await self.db.execute(mailboxes_stmt)
                    mailboxes = mailboxes_result.scalars().all()
                    mailbox_emails = {mb.email.lower() for mb in mailboxes if mb.email}
                    logger.info(f"[CREATE TICKET] Known mailboxes to filter: {mailbox_emails}")
                except Exception as e:
                    logger.warning(f"[CREATE TICKET] Could not get mailbox emails for filtering: {e}")

                # 🔒 FIX: Filter mailboxes from TO recipients (only include real users)
                to_emails = [
                    to.address for to in email.to_recipients
                    if to.address and to.address.lower() not in mailbox_emails
                ]
                to_recipients_str = ", ".join(to_emails) if to_emails else None

                # 🔒 FIX: Filter mailboxes from CC recipients (only include real users)
                cc_emails = [
                    cc.address for cc in email.cc_recipients
                    if cc.address and cc.address.lower() not in mailbox_emails
                ]
                cc_recipients_str = ", ".join(cc_emails) if cc_emails else None

            if to_recipients_str:
                logger.info(f"Ticket from email will have TO recipients: {to_recipients_str}")
            if cc_recipients_str:
                logger.info(f"Ticket from email will have CC recipients: {cc_recipients_str}")
            
            if not user: logger.error(f"Could not get or create user for email: {email.sender.address} in workspace {workspace_id}"); return None
            # Cache user properties to avoid lazy loading issues later
            user_name = user.name if user else 'Unknown'
            user_email = user.email if user else ''
            company_id = user.company_id; assigned_agent = None
            if config.auto_assign and config.default_assignee_id:
                agent_stmt = select(Agent).filter(Agent.id == config.default_assignee_id)
                agent_result = await self.db.execute(agent_stmt)
                assigned_agent = agent_result.scalar_one_or_none()

            workspace_stmt = select(Workspace).filter(Workspace.id == config.workspace_id)
            workspace_result = await self.db.execute(workspace_stmt)
            workspace = workspace_result.scalar_one_or_none()
            if not workspace: logger.error(f"Workspace ID {config.workspace_id} not found. Skipping ticket creation."); return None
            due_date = datetime.utcnow() + timedelta(days=3)
            team_id = None
            if config.mailbox_connection_id:
                from app.models.microsoft import mailbox_team_assignments
                team_stmt = select(mailbox_team_assignments).filter(
                    mailbox_team_assignments.c.mailbox_connection_id == config.mailbox_connection_id
                )
                team_result = await self.db.execute(team_stmt)
                team_assignment = team_result.first()

                if team_assignment:
                    team_id = team_assignment.team_id
            if original_email and original_name:
                forwarded_by_email = email.sender.address
                forwarded_by_name = email.sender.name
                if forwarded_by_name and forwarded_by_name.strip():
                    forwarded_by_formatted = f"{forwarded_by_name} <{forwarded_by_email}>"
                else:
                    forwarded_by_formatted = forwarded_by_email
                
                if cc_recipients_str:
                    cc_recipients_str = f"{cc_recipients_str}, {forwarded_by_formatted}"
                else:
                    cc_recipients_str = forwarded_by_formatted
                logger.info(f"[FORWARD DETECTION] Added forwarder to CC: {forwarded_by_formatted}")
                email_sender_field = f"{original_name} <{original_email}>"
            else:
                email_sender_field = f"{email.sender.name} <{email.sender.address}>"
            task = Task(
                title=email.subject or "No Subject", description=None, status="Unread", priority=priority,
                assignee_id=assigned_agent.id if assigned_agent else None, due_date=due_date, sent_from_id=system_agent.id,
                user_id=user.id, company_id=company_id, workspace_id=workspace.id,
                mailbox_connection_id=config.mailbox_connection_id, team_id=team_id,
                email_message_id=email.id, email_internet_message_id=email.internet_message_id, email_conversation_id=email.conversation_id,
                email_sender=email_sender_field, to_recipients=to_recipients_str, cc_recipients=cc_recipients_str,
                last_update=datetime.utcnow())
            self.db.add(task); await self.db.flush()

            # 🔍 DEBUG: Log the ticket recipients after creation
            logger.info(f"[TICKET CREATED] Ticket #{task.id} saved with recipients:")
            logger.info(f"  📧 Email Sender: {task.email_sender}")
            logger.info(f"  📨 TO recipients: {task.to_recipients}")
            logger.info(f"  📬 CC recipients: {task.cc_recipients}")
            logger.info(f"  📮 BCC recipients: {task.bcc_recipients}")
            
            # Use original email sender name for forwarded emails, otherwise use direct sender
            activity_sender_name = original_name if original_name else email.sender.name
            activity = Activity(agent_id=None, source_type='Ticket', source_id=task.id, workspace_id=workspace.id, action=f"{activity_sender_name} logged a new ticket")
            self.db.add(activity)
            attachments_for_comment = []
            if email.attachments:
                non_inline_attachments = [att for att in email.attachments if not att.is_inline and att.contentBytes]
                for att in non_inline_attachments:
                    try:
                        decoded_bytes = base64.b64decode(att.contentBytes)
                        s3_url = None
                        try:
                            from app.services.s3_service import get_s3_service
                            s3_service = get_s3_service()
                            folder = "images" if att.content_type.startswith("image/") else "documents"
                            s3_url = s3_service.upload_file(
                                file_content=decoded_bytes,
                                filename=att.name,
                                content_type=att.content_type,
                                folder=folder
                            )
                            
                            logger.info(f"📎 Adjunto inicial '{att.name}' subido a S3: {s3_url}")
                            
                        except Exception as s3_error:
                            logger.error(f"❌ Error subiendo adjunto inicial '{att.name}' a S3: {str(s3_error)}")
                            pass
                        db_attachment = TicketAttachment(
                            file_name=att.name,
                            content_type=att.content_type,
                            file_size=att.size,
                            s3_url=s3_url, 
                            content_bytes=decoded_bytes if not s3_url else None 
                        )
                        attachments_for_comment.append(db_attachment)
                    except Exception as e:
                        logger.error(f"Error al procesar adjunto '{att.name}' para ticket {task.id}: {e}", exc_info=True)
            processed_html = self._process_html_body(email.body_content, email.attachments, f"new ticket {task.id}")
            processed_html = re.sub(r'^<p><strong>From:</strong>.*?</p>', '', processed_html, flags=re.DOTALL | re.IGNORECASE)
            if original_email and original_name:
                forward_sender_name = email.sender.name or "Unknown Forwarder"
                forward_sender_email = email.sender.address
                special_metadata = f'<original-sender>{forward_sender_name}|{forward_sender_email}</original-sender>'
                logger.info(f"[FORWARD DETECTION] Conversation will show forwarder: {forward_sender_name} <{forward_sender_email}>")
            else:
                special_metadata = f'<original-sender>{user.name}|{user.email}</original-sender>'
            content_to_store = special_metadata + processed_html
            s3_html_url = None    
            try:
                if content_to_store and content_to_store.strip():
                    from app.services.s3_service import get_s3_service
                    s3_service = get_s3_service()
                    content_length = len(content_to_store)
                    should_migrate_to_s3 = (
                        content_length > 65000 or  
                        s3_service.should_store_html_in_s3(content_to_store)
                                        )              
                    if should_migrate_to_s3:
                        import uuid
                        temp_id = str(uuid.uuid4())
                        s3_url = s3_service.upload_html_content(
                            html_content=content_to_store,
                            filename=f"temp-initial-comment-{temp_id}.html",
                            folder="comments"
                        )
                        s3_html_url = s3_url
                        content_to_store = f"[MIGRATED_TO_S3] Content moved to S3: {s3_url}"
            except Exception as e:
                logger.error(f"❌ [MAIL SYNC] Error pre-migrating initial content to S3: {str(e)}")
                content_to_store = special_metadata + processed_html
                s3_html_url = None
            initial_comment = Comment(
                ticket_id=task.id,
                agent_id=system_agent.id, 
                workspace_id=workspace.id,
                content=content_to_store, 
                s3_html_url=s3_html_url, 
                is_private=False
            )
            for attachment in attachments_for_comment:
                initial_comment.attachments.append(attachment)
                
            self.db.add(initial_comment)
            if s3_html_url and not s3_html_url.endswith(f"comment-{initial_comment.id}.html"):
                try:
                    await self.db.flush()
                    from app.services.s3_service import get_s3_service
                    s3_service = get_s3_service()
                    if '[MIGRATED_TO_S3] Content moved to S3: ' in content_to_store:
                        original_content = special_metadata + processed_html
                    else:
                        original_content = content_to_store
                    final_s3_url = s3_service.store_comment_html(initial_comment.id, original_content)
                    
                    # Actualizar la URL en el comentario
                    initial_comment.s3_html_url = final_s3_url
                    initial_comment.content = f"[MIGRATED_TO_S3] Content moved to S3: {final_s3_url}"
                except Exception as e:
                    logger.warning(f"⚠️ [MAIL SYNC] Could not rename S3 file for initial comment {initial_comment.id}: {str(e)}")
            ticket_body = TicketBody(ticket_id=task.id, email_body="")
            self.db.add(ticket_body)
            await self.db.commit()
            try:
                # Refresh task to avoid lazy loading issues
                task_refreshed_result = await self.db.execute(
                    select(Task).filter(Task.id == task.id)
                )
                task_refreshed = task_refreshed_result.scalar_one_or_none()

                if task_refreshed:
                    task_data = {
                        'id': task_refreshed.id,
                        'title': task_refreshed.title,
                        'status': task_refreshed.status,
                        'priority': task_refreshed.priority,
                        'workspace_id': task_refreshed.workspace_id,
                        'assignee_id': task_refreshed.assignee_id,
                        'team_id': task_refreshed.team_id,
                        'user_id': task_refreshed.user_id,
                        'created_at': task_refreshed.created_at.isoformat() if task_refreshed.created_at else None,
                        'user_name': user_name,
                        'user_email': user_email
                    }
                else:
                    task_data = {
                        'id': task.id,
                        'title': task.title,
                        'status': task.status,
                        'priority': task.priority,
                        'workspace_id': task.workspace_id,
                        'assignee_id': task.assignee_id,
                        'team_id': task.team_id,
                        'user_id': task.user_id,
                        'created_at': task.created_at.isoformat() if task.created_at else None,
                        'user_name': user_name,
                        'user_email': user_email
                    }
                # Use task_refreshed.workspace_id directly to avoid lazy loading issues with workspace object
                from app.core.socketio import emit_new_ticket_sync
                emit_new_ticket_sync(task_refreshed.workspace_id if task_refreshed else task.workspace_id, task_data)
            except Exception as e:
                logger.error(f"❌ [MAIL SYNC] Error emitting Socket.IO event for new ticket {task.id}: {str(e)}")
            try:
                from app.services.automation_service import execute_automations_for_ticket
                from sqlalchemy.orm import joinedload
                task_stmt = select(Task).options(
                    joinedload(Task.user),
                    joinedload(Task.assignee),
                    joinedload(Task.company),
                    joinedload(Task.category),
                    joinedload(Task.team)
                ).filter(Task.id == task.id)
                task_result = await self.db.execute(task_stmt)
                task_with_relations = task_result.scalar_one_or_none()

                if task_with_relations:
                    executed_actions = await execute_automations_for_ticket(self.db, task_with_relations)
                    if executed_actions:
                        # Refresh the task to get updated values from automations
                        await self.db.refresh(task)
                        
            except Exception as automation_error:
                logger.error(f"Error executing automations for new ticket {task.id}: {str(automation_error)}")
            
            # NUEVO: Procesar workflows basados en el contenido del email inicial
            try:
                from app.services.workflow_service import WorkflowService
                
                # Solo procesar si hay contenido significativo
                if email.body_content and email.body_content.strip():
                    workflow_service = WorkflowService(self.db)
                    
                    # Preparar contexto para workflows
                    workflow_context = {
                        'task_id': task.id,
                        'comment_id': initial_comment.id,
                        'agent_id': system_agent.id,  # Agente del sistema que procesa
                        'workspace_id': workspace.id,
                        'task_status': task.status,
                        'task_priority': task.priority,
                        'is_private': False,
                        'is_from_email': True,
                        'is_new_ticket': True,
                        'email_sender': user.email,
                        'email_sender_name': user.name,
                        'assignee_id': task.assignee_id
                    }

                    # Procesar workflows basados en contenido del email inicial
                    workflow_results = await workflow_service.process_message_for_workflows(
                        email.body_content,
                        workspace.id,
                        workflow_context
                    )
                    
                    if workflow_results:
                        logger.info(f"[MAIL SYNC] Executed {len(workflow_results)} workflows for new ticket {task.id}")
                        for result in workflow_results:
                            logger.info(f"[MAIL SYNC] Workflow executed: {result.get('workflow_name')} - {result.get('trigger')}")

                        # Commit any changes made by workflows
                        await self.db.commit()
                    
            except Exception as workflow_error:
                logger.error(f"[MAIL SYNC] Error processing workflows for new ticket: {str(workflow_error)}")
            
            # Verificar si debemos enviar notificaciones (evitar bucles y spam)
            should_send_notification = True
            
            # Evitar notificaciones para correos del sistema o notificaciones automáticas
            notification_keywords = ["ticket", "created", "notification", "system", "auto", "automated", "no-reply", "noreply"]
            system_domains = await self._get_system_domains_for_workspace(workspace.id)  # Detección automática
            
            # Verificar si el asunto parece una notificación automática
            if email.subject:
                subject_lower = email.subject.lower()
                if any(keyword in subject_lower for keyword in notification_keywords):
                    # Si el asunto parece una notificación, reducir la probabilidad de enviar otra notificación
                    if any(domain in email.sender.address.lower() for domain in system_domains):
                        logger.info(f"Skipping notifications for ticket {task.id} as it appears to be a system notification")
                        should_send_notification = False
            if should_send_notification:
                try:
                    from app.services.notification_service import send_notification
                    if user and user.email and not any(domain in user.email.lower() for domain in system_domains):
                        template_vars = {
                            "user_name": user.name,
                            "ticket_id": task.id,
                            "ticket_title": task.title
                        }
                        await send_notification(
                            db=self.db,
                            workspace_id=workspace_id,
                            category="users",
                            notification_type="new_ticket_created",
                            recipient_email=user.email,
                            recipient_name=user.name,
                            template_vars=template_vars,
                            task_id=task.id
                        )
                        logger.info(f"Notification for new ticket {task.id} sent to user {user.name}")
                    
                    # 2. Notificar a miembros del equipo si el ticket está asignado a un equipo sin agente específico
                    if task.team_id and not task.assignee_id:
                        try:
                            from app.services.task_service import send_team_notification
                            await send_team_notification(self.db, task)
                            logger.info(f"Team notification sent for ticket {task.id} assigned to team {task.team_id}")
                        except Exception as team_notify_err:
                            logger.warning(f"Failed to send team notification for ticket {task.id}: {str(team_notify_err)}")
                    
                    # 3. Notificar a todos los agentes activos en el workspace (solo si no es un ticket de equipo)
                    elif not task.team_id:
                        agents_stmt = select(Agent).filter(
                            Agent.workspace_id == workspace_id,
                            Agent.is_active == True,
                            Agent.email != None,
                            Agent.email != ""
                        )
                        agents_result = await self.db.execute(agents_stmt)
                        active_agents = agents_result.scalars().all()
                    
                        # Preparar variables de plantilla para notificaciones de agentes
                        agent_template_vars = {
                            "ticket_id": task.id,
                            "ticket_title": task.title,
                            "user_name": user.name if user else "Unknown User"
                        }
                        
                        # Notificar a cada agente activo
                        for agent in active_agents:
                            # Si el agente es el asignado, añadir información adicional
                            if assigned_agent and agent.id == assigned_agent.id:
                                agent_template_vars["agent_name"] = agent.name
                            else:
                                agent_template_vars["agent_name"] = agent.name

                            # Solo enviar si el agente no está en un dominio del sistema
                            if not any(domain in agent.email.lower() for domain in system_domains):
                                try:
                                    await send_notification(
                                        db=self.db,
                                        workspace_id=workspace_id,
                                        category="agents",
                                        notification_type="new_ticket_created_agent",  # Corregir tipo para agentes
                                        recipient_email=agent.email,
                                        recipient_name=agent.name,
                                        template_vars=agent_template_vars,
                                        task_id=task.id
                                    )
                                    logger.info(f"Notification for new ticket {task.id} sent to agent {agent.name}")
                                except Exception as agent_notify_err:
                                    logger.warning(f"Failed to send notification to agent {agent.name}: {str(agent_notify_err)}")
                    
                except Exception as e:
                    logger.error(f"Error sending notifications for ticket {task.id} created from email: {str(e)}", exc_info=True)
            else:
                logger.info(f"Notifications suppressed for ticket {task.id} to prevent notification loops")
                
            return task
        except DatabaseException as e:
            logger.error(
                f"Database error creating task from email ID {email.id}: {e}",
                extra={
                    "email_id": email.id,
                    "subject": email.subject,
                    "sender": email.sender.address,
                    "workspace_id": config.workspace_id,
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            await self.db.rollback()
            return None
        except Exception as e:
            logger.error(
                f"Unexpected error creating task from email ID {email.id}: {e}",
                extra={
                    "email_id": email.id,
                    "subject": email.subject,
                    "sender": email.sender.address,
                    "workspace_id": config.workspace_id,
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            await self.db.rollback()
            return None

    async def _update_all_email_mappings_for_ticket(self, ticket_id: int, old_email_id: str, new_email_id: str) -> bool:
        """
        Actualiza todos los mappings de email relacionados con un ticket cuando el Message ID cambia.
        Esto es crítico para mantener la consistencia después de mover emails a carpetas.
        Incluye manejo robusto de duplicados y condiciones de carrera.
        """
        if not old_email_id or not new_email_id:
            logger.warning(f"Invalid email IDs provided: old='{old_email_id}', new='{new_email_id}'")
            return False
            
        try:
            # Verificar que el nuevo ID no sea demasiado largo
            if len(new_email_id) > 255:
                logger.warning(f"New email ID is too long ({len(new_email_id)} chars). Truncating to 255 chars.")
                new_email_id = new_email_id[:255]
            
            # Si el ID no cambió, no hay nada que hacer
            if old_email_id == new_email_id:
                logger.debug(f"Email ID unchanged for ticket {ticket_id}. No update needed.")
                return True
            
            logger.info(f"🔄 Updating email mappings for ticket {ticket_id}: {old_email_id[:50]}... → {new_email_id[:50]}...")
            
            # 🔧 ESTRATEGIA COMPLETAMENTE NUEVA: Crear nuevo mapping y eliminar el viejo
            # Esto evita conflictos de transacciones y duplicados
            
            # 1. Verificar si ya existe un mapping con el nuevo ID
            existing_new_stmt = select(EmailTicketMapping).filter(
                EmailTicketMapping.email_id == new_email_id,
                EmailTicketMapping.ticket_id == ticket_id
            )
            existing_new_result = await self.db.execute(existing_new_stmt)
            existing_new_mapping = existing_new_result.scalar_one_or_none()

            if existing_new_mapping:
                logger.info(f"✅ Mapping with new email ID already exists for ticket {ticket_id}. Removing old mappings only.")
                # Solo eliminar los mappings antiguos
                old_mappings_stmt = select(EmailTicketMapping).filter(
                    EmailTicketMapping.ticket_id == ticket_id,
                    EmailTicketMapping.email_id == old_email_id
                )
                old_mappings_result = await self.db.execute(old_mappings_stmt)
                old_mappings = old_mappings_result.scalars().all()

                for old_mapping in old_mappings:
                    await self.db.delete(old_mapping)

                await self.db.commit()
                logger.info(f"✅ Removed {len(old_mappings)} old email mappings for ticket {ticket_id}")
                return True

            # 2. Buscar todos los mappings antiguos para este ticket
            old_mappings_stmt = select(EmailTicketMapping).filter(
                EmailTicketMapping.ticket_id == ticket_id,
                EmailTicketMapping.email_id == old_email_id
            )
            old_mappings_result = await self.db.execute(old_mappings_stmt)
            old_mappings = old_mappings_result.scalars().all()
            
            if not old_mappings:
                logger.debug(f"No old mappings found for ticket {ticket_id} with email ID {old_email_id[:50]}...")
                return False
            
            # 3. Crear nuevos mappings basados en los antiguos
            new_mappings_created = 0
            
            for old_mapping in old_mappings:
                try:
                    # Crear nuevo mapping con el nuevo email ID
                    new_mapping = EmailTicketMapping(
                        email_id=new_email_id,
                        email_conversation_id=old_mapping.email_conversation_id,
                        ticket_id=old_mapping.ticket_id,
                        email_subject=old_mapping.email_subject,
                        email_sender=old_mapping.email_sender,
                        email_received_at=old_mapping.email_received_at,
                        is_processed=old_mapping.is_processed,
                        created_at=old_mapping.created_at,
                        updated_at=datetime.utcnow()
                    )
                    
                    # Intentar agregar el nuevo mapping
                    self.db.add(new_mapping)
                    await self.db.flush()  # Flush para detectar duplicados temprano
                    new_mappings_created += 1

                except Exception as create_error:
                    if "Duplicate entry" in str(create_error):
                        logger.warning(f"🔧 Duplicate detected while creating new mapping for ticket {ticket_id}. Skipping creation.")
                        await self.db.rollback()
                        # Verificar si el mapping ya existe
                        existing_check_stmt = select(EmailTicketMapping).filter(
                            EmailTicketMapping.email_id == new_email_id,
                            EmailTicketMapping.ticket_id == ticket_id
                        )
                        existing_check_result = await self.db.execute(existing_check_stmt)
                        existing_check = existing_check_result.scalar_one_or_none()
                        if existing_check:
                            new_mappings_created += 1  # Contar como exitoso
                    else:
                        logger.error(f"Error creating new mapping for ticket {ticket_id}: {str(create_error)}")
                        await self.db.rollback()
                        continue
            
            # 4. Si se crearon nuevos mappings exitosamente, eliminar los antiguos
            if new_mappings_created > 0:
                try:
                    # Commit los nuevos mappings primero
                    await self.db.commit()

                    # Ahora eliminar los mappings antiguos
                    for old_mapping in old_mappings:
                        await self.db.delete(old_mapping)

                    await self.db.commit()
                    logger.info(f"✅ Successfully updated {new_mappings_created} email mappings for ticket {ticket_id}")
                    return True

                except Exception as cleanup_error:
                    logger.error(f"Error during cleanup for ticket {ticket_id}: {str(cleanup_error)}")
                    await self.db.rollback()
                    return False
            else:
                logger.warning(f"No new mappings were created for ticket {ticket_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error updating email mappings for ticket {ticket_id}: {str(e)}")
            try:
                await self.db.rollback()
            except Exception as rollback_error:
                logger.error(f"Error during rollback for ticket {ticket_id}: {str(rollback_error)}")
            return False

    def _validate_ticket_mailbox_association(self, task: Task, mailbox_connection: MailboxConnection, email_mapping: EmailTicketMapping) -> bool:
        """
        Valida que el ticket esté correctamente asociado con el mailbox correcto.
        En entornos multitenant, esto es crítico para asegurar que las respuestas
        se envíen desde el mailbox correcto.
        """
        try:
            # Verificar que el task tenga un mailbox_connection_id válido
            if not task.mailbox_connection_id:
                logger.error(f"Task {task.id} has no mailbox_connection_id")
                return False
            
            # Verificar que el mailbox_connection existe y está activo
            if not mailbox_connection:
                logger.error(f"Mailbox connection {task.mailbox_connection_id} not found for task {task.id}")
                return False
            
            if not mailbox_connection.is_active:
                logger.error(f"Mailbox connection {mailbox_connection.email} is not active for task {task.id}")
                return False
            
            # Verificar que el mailbox pertenece al mismo workspace
            if mailbox_connection.workspace_id != task.workspace_id:
                logger.error(f"Mailbox {mailbox_connection.email} (workspace {mailbox_connection.workspace_id}) does not match task {task.id} workspace {task.workspace_id}")
                return False
            
            # Verificar que tenemos un mapping válido
            if not email_mapping or not email_mapping.email_id:
                logger.error(f"No valid email mapping found for task {task.id}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating ticket-mailbox association for task {task.id}: {str(e)}")
            return False

    def _process_html_for_email(self, html_content: str) -> str:
        """Procesa el HTML para asegurar un formato limpio y con espaciado controlado en clientes de correo."""
        try:
            if not html_content.strip():
                return '' 

            soup = BeautifulSoup(html_content, 'html.parser')

            # Procesar todos los párrafos primero para limpieza general y márgenes
            for p_tag in soup.find_all('p'):
                # Eliminar estilos en línea preexistentes que no sean de la firma procesada después
                if p_tag.has_attr('style') and not p_tag.find_parent(class_='email-signature'):
                    del p_tag['style'] 
                
                # Aplicar margen base a párrafos que no son de firma
                if not p_tag.find_parent(class_='email-signature'):
                     p_tag['style'] = 'margin: 0.5em 0; padding: 0; line-height: 1.4;' # Estilo base para párrafos normales
                else:
                    # Es un párrafo de firma, se procesará específicamente después
                    pass

            # Procesamiento específico para la firma de correo
            signature_elements = soup.find_all(class_='email-signature')
            for sig_wrapper in signature_elements:
                # Aplicar estilo base al contenedor de la firma si es un div
                if sig_wrapper.name == 'div':
                    sig_wrapper['style'] = 'line-height: 0.6; font-size: 0.9em; color: #6b7280;'
                
                for p_in_sig in sig_wrapper.find_all('p'):
                    p_in_sig['style'] = 'margin: 0 0 0.1em 0; padding: 0; line-height: 0.6; font-size: 0.9em; color: #6b7280;'
                
                # Asegurar que los <br> dentro de la firma tengan line-height mínimo si es necesario (aunque line-height en <br> es poco estándar)
                # Normalmente, el line-height del <p> o <div> contenedor debería ser suficiente.
                # for br_in_sig in sig_wrapper.find_all('br'):
                #     br_in_sig['style'] = 'line-height: 1;' # O incluso quitarlo si no ayuda

            # Eliminar párrafos vacíos que no sean de firma y no contengan imágenes/BRs significativos
            for p_tag in soup.find_all('p'):
                if not p_tag.find_parent(class_='email-signature'):
                    if not p_tag.get_text(strip=True) and not p_tag.find_all(('br', 'img')):
                        prev_sibling = p_tag.find_previous_sibling()
                        if prev_sibling and prev_sibling.name == 'br':
                            p_tag.decompose()
                        else:
                            br_tag = soup.new_tag('br')
                            p_tag.replace_with(br_tag)
            
            processed_html = str(soup)
            processed_html = re.sub(r'(<br\s*/?>\s*){2,}', '<br>\n', processed_html)

            return processed_html
        
        except Exception as e:
            logger.error(f"Error al procesar HTML para correo electrónico: {str(e)}", exc_info=True)
            return html_content

    def send_reply_email(self, task_id: int, reply_content: str, agent: Agent, attachment_ids: List[int] = None, to_recipients: List[str] = None, cc_recipients: List[str] = None, bcc_recipients: List[str] = None) -> bool:
        """
        Send a reply email for a ticket that originated from an email.
        If the ticket has original CC recipients, they will be included in the reply.
        """
        logger.info(f"[REPLY EMAIL] Starting reply process for task {task_id} by agent {agent.name}")
        
        # IMPORTANTE: Forzar refresh para obtener datos actualizados del ticket
        self.db.expire_all()  # Expira cache de SQLAlchemy
        
        # Get the task with its mailbox connection and user information
        task = self.db.query(Task).options(
            joinedload(Task.mailbox_connection),
            joinedload(Task.user)  # Agregar user para debugging
        ).filter(Task.id == task_id).first()
        
        if not task:
            logger.error(f"❌ Task {task_id} not found for reply email")
            return False
        
        # Log información del usuario actual para debugging
        if task.user:
            logger.info(f"[REPLY EMAIL] Task {task_id} assigned to user: {task.user.name} ({task.user.email})")
        else:
            logger.info(f"[REPLY EMAIL] Task {task_id} has no assigned user")
        
        if not task.mailbox_connection:
            logger.error(f"❌ Task {task_id} has no associated mailbox connection. Cannot send reply.")
            return False
        
        mailbox_connection = task.mailbox_connection
        
        # Get email mappings to check original sender
        email_mapping = self.db.query(EmailTicketMapping).filter(
            EmailTicketMapping.ticket_id == task_id
        ).order_by(EmailTicketMapping.created_at.desc()).first()

        if not email_mapping:
            logger.error(f"❌ No email mappings found for ticket {task_id}. Cannot send reply.")
            return False
        
        # Get the original email sender from the first mapping
        original_mapping = email_mapping
        original_sender = original_mapping.email_sender  # Format: "Name <email@domain.com>"
        
        # Extract email from original sender
        email_match = re.search(r'<([^>]+)>', original_sender) if original_sender else None
        original_sender_email = email_match.group(1) if email_match else (original_sender or "")
        
        # Check if the current ticket user is different from the original sender
        current_user_email = task.user.email if task.user else ""
        contact_changed = current_user_email and original_sender_email and current_user_email.lower() != original_sender_email.lower()
        
        if contact_changed:
            logger.info(f"[REPLY EMAIL] 🔄 Primary contact changed from {original_sender_email} to {current_user_email}")
            logger.info(f"[REPLY EMAIL] 📧 Sending NEW email to updated contact instead of reply")
            
            # Send a new email to the updated contact instead of using createReply
            subject = f"Re: [ID:{task_id}] {task.title}"
            
            # Format the HTML content if needed
            if not reply_content.strip().lower().startswith('<html'):
                html_body = f"<html><head><style>body {{ font-family: sans-serif; font-size: 10pt; }} p {{ margin: 0 0 16px 0; padding: 4px 0; min-height: 16px; line-height: 1.5; }}</style></head><body>{reply_content}</body></html>"
            else:
                html_body = reply_content
            
            # Use send_new_email method for the updated contact
            return self.send_new_email(
                mailbox_email=mailbox_connection.email,
                recipient_email=current_user_email,
                subject=subject,
                html_body=html_body,
                attachment_ids=attachment_ids,
                task_id=task_id,
                cc_recipients=cc_recipients
            )
        
        # If contact hasn't changed, proceed with normal reply logic
        logger.info(f"[REPLY EMAIL] 📧 Contact unchanged, sending normal reply to {original_sender_email}")
        
        # Process TO recipients
        all_to_recipients = []
        if to_recipients:
            logger.info(f"[REPLY EMAIL] ✅ Using provided TO recipients from frontend: {to_recipients}")
            all_to_recipients = to_recipients
        else:
            logger.warning(f"[REPLY EMAIL] ⚠️ No TO recipients provided from frontend, falling back to original sender: {original_sender_email}")
            all_to_recipients = [original_sender_email]
        
        logger.info(f"[REPLY EMAIL] 📧 Total TO recipients for this reply: {all_to_recipients}")
        
        # 🔧 NOTA: CC recipients se procesarán después de obtener original_message_id
        
        # Verificar que el token de aplicación (client credentials) no tiene permisos para acceder a mailboxes específicos
        # Necesitamos usar el token delegado del usuario que configuró este mailbox
        try:
            # Obtener el token específico para este mailbox
            mailbox_token = self.db.query(MicrosoftToken).filter(
                MicrosoftToken.mailbox_connection_id == mailbox_connection.id,
                MicrosoftToken.expires_at > datetime.utcnow()
            ).order_by(MicrosoftToken.created_at.desc()).first()
            
            if not mailbox_token:
                # Intentar refrescar token expirado
                logger.warning(f"No active token found for mailbox {mailbox_connection.email}. Looking for refreshable token...")
                expired_token = self.db.query(MicrosoftToken).filter(
                    MicrosoftToken.mailbox_connection_id == mailbox_connection.id,
                    MicrosoftToken.refresh_token.isnot(None),
                    MicrosoftToken.refresh_token != ""
                ).order_by(MicrosoftToken.expires_at.desc()).first()
                
                if expired_token:
                    try:
                        from app.services.microsoft_auth_service import MicrosoftAuthService
                        auth_service = MicrosoftAuthService(self.db, None, None)
                        mailbox_token = auth_service.refresh_token(expired_token)
                    except Exception as refresh_error:
                        logger.error(f"Failed to refresh token for mailbox {mailbox_connection.email}: {str(refresh_error)}")
                        return False
                else:
                    logger.error(f"No refreshable token found for mailbox {mailbox_connection.email}")
                    return False
            
            if not mailbox_token:
                logger.error(f"Could not obtain valid token for mailbox {mailbox_connection.email}")
                return False
                
            # Usar el token del usuario específico del mailbox
            app_token = mailbox_token.access_token
            
        except (DatabaseException, MicrosoftAPIException) as e:
            logger.error(
                f"Error getting user token for mailbox {mailbox_connection.email}: {e}",
                extra={
                    "mailbox_email": mailbox_connection.email,
                    "task_id": task_id,
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            return False
        except Exception as e:
            logger.error(
                f"Unexpected error getting user token for mailbox {mailbox_connection.email}: {e}",
                extra={
                    "mailbox_email": mailbox_connection.email,
                    "task_id": task_id,
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            return False

        original_message_id = email_mapping.email_id
        
        # 🔧 ROBUST FIX: Combine all available CC sources to prevent data loss.
        logger.info(f"[CC DEBUG] --- Starting CC recipient processing for task {task_id} ---")
        final_cc_recipients = set()

        # 1. Use CCs provided by the frontend in this specific reply.
        if cc_recipients:
            logger.info(f"[CC DEBUG] Source 1: Frontend. Found {len(cc_recipients)} recipients: {cc_recipients}")
            for email in cc_recipients:
                final_cc_recipients.add(email.strip().lower())
        else:
            logger.info(f"[CC DEBUG] Source 1: Frontend. No CC recipients provided.")
        
        # 2. Also include CCs stored with the ticket in the database.
        if task.cc_recipients:
            ticket_cc_recipients = [email.strip().lower() for email in task.cc_recipients.split(",") if email.strip()]
            if ticket_cc_recipients:
                logger.info(f"[CC DEBUG] Source 2: Database. Found {len(ticket_cc_recipients)} recipients: {ticket_cc_recipients}")
                for email in ticket_cc_recipients:
                    final_cc_recipients.add(email)
            else:
                logger.info(f"[CC DEBUG] Source 2: Database. 'cc_recipients' field is present but empty.")
        else:
            logger.info(f"[CC DEBUG] Source 2: Database. No 'cc_recipients' field on task.")

        # 3. As a last resort, try fetching from the original email.
        # This logic is now a fallback if the other sources yield nothing.
        logger.info(f"[CC DEBUG] Current CC list size before fallback: {len(final_cc_recipients)}")
        if not final_cc_recipients:
            logger.info("[CC DEBUG] Source 3: Fallback. No CCs from frontend or DB, attempting to fetch from original email.")
            try:
                message_data = self.graph_client.get_mailbox_email_content(app_token, mailbox_connection.email, original_message_id)
                if message_data:
                    cc_recipients_data = message_data.get("ccRecipients", [])
                    logger.info(f"[CC DEBUG] Fallback: Successfully fetched original email. Found {len(cc_recipients_data)} raw CC entries.")
                    for cc_recipient in cc_recipients_data:
                        email_address = cc_recipient.get("emailAddress", {}).get("address")
                        if email_address:
                            final_cc_recipients.add(email_address.strip().lower())
                    if final_cc_recipients:
                        logger.info(f"[CC DEBUG] Fallback: Added {len(final_cc_recipients)} recipients from original email.")
                else:
                    # This is where the 404 error would have been caught and logged by the graph_client
                    logger.warning(f"[CC DEBUG] Fallback: Could not fetch original message content for message ID {original_message_id}. Cannot get CC recipients from this source.")
            except Exception as cc_error:
                logger.error(f"[CC DEBUG] Fallback: An exception occurred while fetching original CC recipients: {str(cc_error)}")

        cc_recipients = list(final_cc_recipients)
        logger.info(f"[CC DEBUG] --- Final CC List ---")
        if cc_recipients:
            logger.info(f"[CC DEBUG] Total unique CC recipients to be used: {len(cc_recipients)}")
            logger.info(f"[CC DEBUG] Final list: {cc_recipients}")
        else:
            logger.info("[CC DEBUG] No CC recipients will be included in this reply.")
        logger.info(f"[CC DEBUG] --- End of CC processing ---")
        if cc_recipients:
            cleaned_cc_recipients = []
            for cc_email in cc_recipients:
                
                cleaned_email = cc_email.strip()
                email_match = re.search(r'<([^>]+)>', cleaned_email)
                if email_match:
                    cleaned_email = email_match.group(1).strip()
                if ' ' in cleaned_email:
                    email_pattern = r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'
                    email_matches = re.findall(email_pattern, cleaned_email)
                    if email_matches:
                        cleaned_email = email_matches[0]
                if cleaned_email and '@' in cleaned_email and '.' in cleaned_email and cleaned_email not in cleaned_cc_recipients:
                    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                    if re.match(email_pattern, cleaned_email):
                        cleaned_cc_recipients.append(cleaned_email)
                    else:
                        logger.warning(f"Invalid email format after cleaning: {cleaned_email} (original: {cc_email})")
            
            cc_recipients = cleaned_cc_recipients
            logger.info(f"✅ Cleaned CC recipients for Microsoft Graph: {cc_recipients}")
        if not self._validate_ticket_mailbox_association(task, mailbox_connection, email_mapping):
            return False

        subject = f"Re: {task.title}"
        processed_html = self._process_html_for_email(reply_content)

        # Enviar como un nuevo correo pero manteniendo el ID de conversación
        # Si hay múltiples destinatarios TO, enviar a todos
        if len(all_to_recipients) == 1:
            success = self.send_new_email(
                mailbox_email=mailbox_connection.email,
                recipient_email=all_to_recipients[0],
                subject=subject,
                html_body=processed_html,
                attachment_ids=attachment_ids,
                task_id=task_id,
                cc_recipients=cc_recipients,
                bcc_recipients=bcc_recipients,
                conversation_id=email_mapping.email_conversation_id
            )
        else:
            # Múltiples destinatarios TO - usar send_new_email_multiple_recipients
            success = self.send_new_email_multiple_recipients(
                mailbox_email=mailbox_connection.email,
                recipient_emails=all_to_recipients,
                subject=subject,
                html_body=processed_html,
                attachment_ids=attachment_ids,
                task_id=task_id,
                cc_recipients=cc_recipients,
                bcc_recipients=bcc_recipients,
                conversation_id=email_mapping.email_conversation_id
            )

        if success:
            logger.info(f"✅ Successfully sent reply for ticket {task_id} from mailbox {mailbox_connection.email}")
            try:
                from app.services.task_service import _execute_workflows_thread
                import threading
                update_data = {'reply_sent': True}
                threading.Thread(
                    target=_execute_workflows_thread,
                    args=(task_id, task.workspace_id, None, task.status, task.priority, update_data),
                    daemon=True
                ).start()
                logger.info(f"🚀 Background workflow processes queued for ticket {task_id}")
                from app.core.socketio import emit_ticket_update_sync
                emit_ticket_update_sync(task.workspace_id, task_id)
                logger.info(f"📤 Emitted ticket_updated to workspace {task.workspace_id}")
            except ImportError:
                logger.error(f"Could not import _execute_workflows_thread. Skipping background workflows for ticket {task_id}.")
            except Exception as post_send_err:
                logger.error(f"Error in post-send operations for ticket {task_id}: {post_send_err}")
        return success

    def send_new_email(self, mailbox_email: str, recipient_email: str, subject: str, html_body: str, attachment_ids: List[int] = None, task_id: Optional[int] = None, cc_recipients: List[str] = None, bcc_recipients: List[str] = None, conversation_id: Optional[str] = None) -> bool:
        logger.info(f"Attempting to send new email from: {mailbox_email} to: {recipient_email} with subject: {subject}")
        try:
            mailbox_connection = self.db.query(MailboxConnection).filter(
                MailboxConnection.email == mailbox_email,
                MailboxConnection.is_active == True
            ).first()
            
            if not mailbox_connection:
                logger.error(f"Mailbox connection not found for email: {mailbox_email}")
                return False
            mailbox_token = self.db.query(MicrosoftToken).filter(
                MicrosoftToken.mailbox_connection_id == mailbox_connection.id,
                MicrosoftToken.expires_at > datetime.utcnow()
            ).order_by(MicrosoftToken.created_at.desc()).first()
            
            if not mailbox_token:
                logger.warning(f"No active token found for mailbox {mailbox_email}. Looking for refreshable token...")
                expired_token = self.db.query(MicrosoftToken).filter(
                    MicrosoftToken.mailbox_connection_id == mailbox_connection.id,
                    MicrosoftToken.refresh_token.isnot(None),
                    MicrosoftToken.refresh_token != ""
                ).order_by(MicrosoftToken.expires_at.desc()).first()
                
                if expired_token:
                    try:
                        from app.services.microsoft_auth_service import MicrosoftAuthService
                        auth_service = MicrosoftAuthService(self.db, None, None)
                        mailbox_token = auth_service.refresh_token(expired_token)
                    except Exception as refresh_error:
                        logger.error(f"Failed to refresh token for mailbox {mailbox_email}: {str(refresh_error)}")
                        return False
                else:
                    logger.error(f"No refreshable token found for mailbox {mailbox_email}")
                    return False
            
            if not mailbox_token:
                logger.error(f"Could not obtain valid token for mailbox {mailbox_email}")
                return False
            app_token = mailbox_token.access_token
            
        except Exception as e: 
            logger.error(f"Failed to get user token for mailbox {mailbox_email}: {e}"); 
            return False
        html_body = self._process_html_for_email(html_body)
        attachments_data = []
        if attachment_ids and len(attachment_ids) > 0:
            for attachment_id in attachment_ids:
                attachment = self.db.query(TicketAttachment).filter(TicketAttachment.id == attachment_id).first()
                if attachment:
                    file_content = None
                    if attachment.content_bytes:
                        file_content = attachment.content_bytes
                        logger.info(f"Using content_bytes for attachment {attachment.file_name} (ID: {attachment_id}) in new email")
                    elif attachment.s3_url:
                        logger.info(f"Downloading attachment {attachment.file_name} from S3: {attachment.s3_url} for new email")
                        from app.services.s3_service import get_s3_service
                        s3_service = get_s3_service()
                        file_content = s3_service._download_file_from_s3(attachment.s3_url)
                        if not file_content:
                            logger.error(f"Failed to download attachment {attachment.file_name} from S3 for new email")
                            continue
                    else:
                        logger.error(f"Attachment {attachment.file_name} (ID: {attachment_id}) has no content_bytes or s3_url for new email")
                        continue
                    content_b64 = base64.b64encode(file_content).decode('utf-8')
                    attachments_data.append({
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": attachment.file_name,
                        "contentType": attachment.content_type,
                        "contentBytes": content_b64
                    })
                    logger.info(f"Added attachment {attachment.file_name} ({attachment.id}) to new email")
                else:
                    logger.warning(f"Attachment ID {attachment_id} not found when preparing email")
        if not html_body.strip().lower().startswith('<html'):
            html_body = f"<html><head><style>body {{ font-family: sans-serif; font-size: 10pt; }} p {{ margin: 0 0 16px 0; padding: 4px 0; min-height: 16px; line-height: 1.5; }}</style></head><body>{html_body}</body></html>"
        original_subject = subject.strip()
        if task_id:
            ticket_id_tag = f"[ID:{task_id}]"
            if ticket_id_tag not in original_subject:
                new_subject = f"{ticket_id_tag} {original_subject}"
                logger.info(f"Modified subject for task {task_id} from '{original_subject}' to '{new_subject}'")
                subject = new_subject
            else:
                logger.info(f"Subject already contains ticket ID tag: '{original_subject}'")
        email_payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "HTML", "content": html_body},
                "toRecipients": [{"emailAddress": {"address": recipient_email}}]
            },
            "saveToSentItems": "true"
        }
        if conversation_id:
            email_payload["message"]["conversationId"] = conversation_id
            logger.info(f"Replying within conversation ID: {conversation_id}")
        if cc_recipients:
            cleaned_cc_recipients = []
            for cc_email in cc_recipients:
                cleaned_email = cc_email.strip()
                email_match = re.search(r'<([^>]+)>', cleaned_email)
                if email_match:
                    cleaned_email = email_match.group(1).strip()
                if ' ' in cleaned_email:
                    email_pattern = r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'
                    email_matches = re.findall(email_pattern, cleaned_email)
                    if email_matches:
                        cleaned_email = email_matches[0]
                if cleaned_email and '@' in cleaned_email and '.' in cleaned_email and cleaned_email not in cleaned_cc_recipients:
                    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                    if re.match(email_pattern, cleaned_email):
                        cleaned_cc_recipients.append(cleaned_email)
                    else:
                        logger.warning(f"Invalid email format after cleaning: {cleaned_email} (original: {cc_email})")
            
            if cleaned_cc_recipients:
                email_payload["message"]["ccRecipients"] = [{"emailAddress": {"address": email}} for email in cleaned_cc_recipients]
                logger.info(f"Including {len(cleaned_cc_recipients)} cleaned CC recipients in new email: {cleaned_cc_recipients}")
            else:
                logger.warning("No valid CC recipients after cleaning")
        if bcc_recipients:
            email_payload["message"]["bccRecipients"] = [{"emailAddress": {"address": email}} for email in bcc_recipients]
            logger.info(f"Including {len(bcc_recipients)} BCC recipients in new email: {bcc_recipients}")
        if attachments_data:
            email_payload["message"]["attachments"] = attachments_data
            logger.info(f"Including {len(attachments_data)} attachments in new email")
        
        try:
            send_mail_endpoint = f"{self.graph_client.graph_url}/users/{mailbox_email}/sendMail"
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
            logger.debug(f"Sending new email via endpoint: {send_mail_endpoint}")
            response = requests.post(send_mail_endpoint, headers=headers, json=email_payload)
            if response.status_code not in [200, 202]:
                error_details = "No details available"; 
                try: error_details = response.json()
                except ValueError: error_details = response.text
                logger.error(f"Failed to send new email from {mailbox_email} to {recipient_email}. Status Code: {response.status_code}. Details: {error_details}")
                response.raise_for_status()
            logger.info(f"Successfully sent new email from {mailbox_email} to {recipient_email} (via /sendMail endpoint)")
            return True
        except requests.exceptions.RequestException as e:
            error_details = "No details available"; status_code = 'N/A'
            if e.response is not None:
                status_code = e.response.status_code
                try: error_details = e.response.json()
                except ValueError: error_details = e.response.text
            logger.error(f"Failed to send new email from {mailbox_email} to {recipient_email}. Status Code: {status_code}. Details: {error_details}. Error: {str(e)}")
            return False
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while sending new email from {mailbox_email} to {recipient_email}. Error: {str(e)}",
                extra={
                    "mailbox_email": mailbox_email,
                    "recipient_email": recipient_email,
                    "task_id": task_id,
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            return False

    def send_new_email_multiple_recipients(self, mailbox_email: str, recipient_emails: List[str], subject: str, html_body: str, attachment_ids: List[int] = None, task_id: Optional[int] = None, cc_recipients: List[str] = None, bcc_recipients: List[str] = None, conversation_id: Optional[str] = None) -> bool:
        logger.info(f"Attempting to send new email from: {mailbox_email} to multiple recipients: {recipient_emails} with subject: {subject}")
        try:
            mailbox_connection = self.db.query(MailboxConnection).filter(
                MailboxConnection.email == mailbox_email,
                MailboxConnection.is_active == True
            ).first()
            
            if not mailbox_connection:
                logger.error(f"Mailbox connection not found for email: {mailbox_email}")
                return False
            
            mailbox_token = self.db.query(MicrosoftToken).filter(
                MicrosoftToken.mailbox_connection_id == mailbox_connection.id,
                MicrosoftToken.expires_at > datetime.utcnow()
            ).order_by(MicrosoftToken.created_at.desc()).first()
            
            if not mailbox_token:
                logger.warning(f"No active token found for mailbox {mailbox_email}. Looking for refreshable token...")
                expired_token = self.db.query(MicrosoftToken).filter(
                    MicrosoftToken.mailbox_connection_id == mailbox_connection.id,
                    MicrosoftToken.refresh_token.isnot(None),
                    MicrosoftToken.refresh_token != ""
                ).order_by(MicrosoftToken.expires_at.desc()).first()
                
                if expired_token:
                    try:
                        mailbox_token = self.auth_service.refresh_token(expired_token)
                    except Exception as refresh_error:
                        logger.error(f"Failed to refresh token for mailbox {mailbox_email}: {str(refresh_error)}")
                        return False
                else:
                    logger.error(f"No refreshable token found for mailbox {mailbox_email}")
                    return False
                    
            if not mailbox_token:
                logger.error(f"Could not obtain valid token for mailbox {mailbox_email}")
                return False
            
            app_token = mailbox_token.access_token
            html_body = self._process_html_for_email(html_body)
            
            # Process subject with task ID if needed
            original_subject = subject.strip()
            if task_id:
                ticket_id_tag = f"[ID:{task_id}]"
                if ticket_id_tag not in original_subject:
                    new_subject = f"{ticket_id_tag} {original_subject}"
                    logger.info(f"Modified subject for task {task_id} from '{original_subject}' to '{new_subject}'")
                    subject = new_subject
                else:
                    logger.info(f"Subject already contains ticket ID tag: '{original_subject}'")
            
            # Build email payload with multiple TO recipients
            email_payload = {
                "message": {
                    "subject": subject,
                    "body": {"contentType": "HTML", "content": html_body},
                    "toRecipients": [{"emailAddress": {"address": email}} for email in recipient_emails]
                },
                "saveToSentItems": "true"
            }
            
            # Add conversation ID if provided
            if conversation_id:
                email_payload["message"]["conversationId"] = conversation_id
                logger.info(f"Replying within conversation ID: {conversation_id}")
            
            # Process attachments
            attachments_data = []
            if attachment_ids:
                try:
                    for attachment_id in attachment_ids:
                        attachment = self.db.query(TicketAttachment).filter(TicketAttachment.id == attachment_id).first()
                        if attachment:
                            file_content = None
                            if attachment.content_bytes:
                                file_content = attachment.content_bytes
                                logger.info(f"Using content_bytes for attachment {attachment.file_name} (ID: {attachment_id}) in reply")
                            elif attachment.s3_url:
                                logger.info(f"Downloading attachment {attachment.file_name} from S3: {attachment.s3_url} for reply")
                                from app.services.s3_service import get_s3_service
                                s3_service = get_s3_service()
                                file_content = s3_service._download_file_from_s3(attachment.s3_url)
                                if not file_content:
                                    logger.error(f"Failed to download attachment {attachment.file_name} from S3 for reply")
                                    continue
                            else:
                                logger.error(f"Attachment {attachment.file_name} (ID: {attachment_id}) has no content_bytes or s3_url for reply")
                                continue

                            content_b64 = base64.b64encode(file_content).decode('utf-8')
                            attachment_data = {
                                "@odata.type": "#microsoft.graph.fileAttachment",
                                "name": attachment.file_name,
                                "contentType": attachment.content_type,
                                "contentBytes": content_b64
                            }
                            attachments_data.append(attachment_data)
                            logger.info(f"Added attachment {attachment.file_name} ({attachment.id}) to reply email")
                        else:
                            logger.warning(f"Attachment ID {attachment_id} not found when preparing reply")
                except Exception as attach_error:
                    logger.error(f"Error processing attachments: {str(attach_error)}")
            
            # Process CC recipients
            if cc_recipients:
                cleaned_cc_recipients = []
                for cc_email in cc_recipients:
                    cleaned_email = cc_email.strip()
                    email_match = re.search(r'<([^>]+)>', cleaned_email)
                    if email_match:
                        cleaned_email = email_match.group(1).strip()
                    if ' ' in cleaned_email:
                        email_pattern = r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'
                        email_matches = re.findall(email_pattern, cleaned_email)
                        if email_matches:
                            cleaned_email = email_matches[0]
                    if cleaned_email and '@' in cleaned_email and '.' in cleaned_email and cleaned_email not in cleaned_cc_recipients:
                        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                        if re.match(email_pattern, cleaned_email):
                            cleaned_cc_recipients.append(cleaned_email)
                        else:
                            logger.warning(f"Invalid email format after cleaning: {cleaned_email} (original: {cc_email})")
                
                if cleaned_cc_recipients:
                    email_payload["message"]["ccRecipients"] = [{"emailAddress": {"address": email}} for email in cleaned_cc_recipients]
                    logger.info(f"Including {len(cleaned_cc_recipients)} cleaned CC recipients in multiple recipient email: {cleaned_cc_recipients}")
            
            # Process BCC recipients
            if bcc_recipients:
                email_payload["message"]["bccRecipients"] = [{"emailAddress": {"address": email}} for email in bcc_recipients]
                logger.info(f"Including {len(bcc_recipients)} BCC recipients in multiple recipient email: {bcc_recipients}")
            
            # Add attachments
            if attachments_data:
                email_payload["message"]["attachments"] = attachments_data
                logger.info(f"Including {len(attachments_data)} attachments in multiple recipient email")
            
            try:
                send_mail_endpoint = f"{self.graph_client.graph_url}/users/{mailbox_email}/sendMail"
                headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
                logger.debug(f"Sending multiple recipient email via endpoint: {send_mail_endpoint}")
                response = requests.post(send_mail_endpoint, headers=headers, json=email_payload)
                
                if response.status_code not in [200, 202]:
                    error_details = "No details available"
                    try: 
                        error_details = response.json()
                    except ValueError: 
                        error_details = response.text
                    logger.error(f"Failed to send multiple recipient email from {mailbox_email} to {recipient_emails}. Status Code: {response.status_code}. Details: {error_details}")
                    response.raise_for_status()
                
                logger.info(f"Successfully sent multiple recipient email from {mailbox_email} to {recipient_emails} (via /sendMail endpoint)")
                return True
                
            except requests.exceptions.RequestException as e:
                error_details = "No details available"
                status_code = 'N/A'
                if e.response is not None:
                    status_code = e.response.status_code
                    try: 
                        error_details = e.response.json()
                    except ValueError: 
                        error_details = e.response.text
                logger.error(f"Failed to send multiple recipient email from {mailbox_email} to {recipient_emails}. Status Code: {status_code}. Details: {error_details}. Error: {str(e)}")
                return False
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while sending multiple recipient email from {mailbox_email} to {recipient_emails}. Error: {str(e)}",
                extra={
                    "mailbox_email": mailbox_email,
                    "recipient_emails": recipient_emails,
                    "task_id": task_id,
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            return False

    async def send_email_with_user_token(
        self, user_access_token: str, sender_mailbox_email: str, recipient_email: str, 
        subject: str, html_body: str, task_id: Optional[int] = None
    ) -> bool:
        if not user_access_token:
            logger.error("Token is None or empty. Cannot send email.")
            return False
        html_body = self._process_html_for_email(html_body)
        if not html_body.strip().lower().startswith('<html'):
            html_body = f"<html><head><style>body {{ font-family: sans-serif; font-size: 10pt; }} p {{ margin: 0 0 16px 0; padding: 4px 0; min-height: 16px; line-height: 1.5; }}</style></head><body>{html_body}</body></html>"
        original_subject = subject.strip()
        if task_id:
            ticket_id_tag = f"[ID:{task_id}]"
            if ticket_id_tag not in original_subject:
                new_subject = f"{ticket_id_tag} {original_subject}"
                logger.info(f"Modified subject for task {task_id} from '{original_subject}' to '{new_subject}'")
                subject = new_subject
            else:
                logger.info(f"Subject already contains ticket ID tag: '{original_subject}'")
        
        email_payload = {
            "message": {"subject": subject, "body": {"contentType": "HTML", "content": html_body},
                        "toRecipients": [{"emailAddress": {"address": recipient_email}}]},
            "saveToSentItems": "true"}
        try:
            send_mail_endpoint = f"{self.graph_client.graph_url}/users/{sender_mailbox_email}/sendMail"
            headers = {"Authorization": f"Bearer {user_access_token}", "Content-Type": "application/json"}
            
            async with httpx.AsyncClient() as client:
                response = await client.post(send_mail_endpoint, headers=headers, json=email_payload, timeout=30.0)
            
            if response.status_code not in [200, 202]:
                error_details = "No details available"; 
                try: 
                    error_details = response.json()
                    logger.error(f"Detailed error response: {error_details}")
                except Exception: 
                    error_details = response.text
                    logger.error(f"Error response text: {error_details}")
                    
                logger.error(f"Failed to send email from {sender_mailbox_email} using user token. Status: {response.status_code}. Details: {error_details}")
                response.raise_for_status() 
                
            logger.info(f"📧 Email sent to {recipient_email}")
            return True
        except httpx.HTTPStatusError as e:
            error_details = "No details available"; 
            try: 
                error_details = e.response.json()
                logger.error(f"Detailed error response in exception: {error_details}")
            except Exception: 
                error_details = e.response.text
                logger.error(f"Error response text in exception: {error_details}")
                
            logger.error(f"HTTP error sending email from {sender_mailbox_email} using user token. Status: {e.response.status_code}. Details: {error_details}. Error: {str(e)}")
            return False
        except httpx.TimeoutException as e:
            logger.error(f"Timeout error sending email from {sender_mailbox_email}: {str(e)}")
            return False
        except Exception as e:
            logger.error(
                f"Error sending email from {sender_mailbox_email} using user token: {e}",
                extra={
                    "sender_mailbox_email": sender_mailbox_email,
                    "recipient_email": recipient_email,
                    "task_id": task_id,
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            return False

    async def _get_system_domains_for_workspace(self, workspace_id: int) -> List[str]:

        try:
            core_system_domains = ["enque.cc", "microsoftexchange"]


            mailbox_stmt = select(MailboxConnection).filter(
                MailboxConnection.workspace_id == workspace_id,
                MailboxConnection.is_active == True
            )
            mailbox_result = await self.db.execute(mailbox_stmt)
            mailbox_connections = mailbox_result.scalars().all()

            workspace_domains = set()
            for mailbox in mailbox_connections:
                if mailbox.email and '@' in mailbox.email:
                    domain = mailbox.email.split('@')[-1].lower()
                    workspace_domains.add(domain)


            all_system_domains = core_system_domains + list(workspace_domains)
            

            
            return all_system_domains
            
        except Exception as e:
            logger.error(f"Error detecting system domains for workspace {workspace_id}: {str(e)}")
            return ["enque.cc", "microsoftexchange"]
