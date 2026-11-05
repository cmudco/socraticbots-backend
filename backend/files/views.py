# backend/files/views.py
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django.http import FileResponse, Http404
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import action

from bots.models import Bot
from users.authentication import JWTAuthentication
from utils.dare_api import files_client, DareApiError


def convert_dare_file_to_bot_file(dare_file):
    """
    Act as pure proxy - return DARE file data directly without conversion
    """
    return dare_file


class HasBotAccess(permissions.BasePermission):
    """
    Custom permission to check if user has access to this bot's files.
    """
    def has_permission(self, request, view):
        bot_id = view.kwargs.get('bot_id')
        
        try:
            bot = Bot.objects.get(id=bot_id)
        except Bot.DoesNotExist:
            return False
            
        user = request.user
        
        # Check if user is bot owner or collaborator via bot_group
        if bot.user.id == user.id:
            return True
            
        # Check if user is collaborator on the bot group
        if bot.bot_group.collaborators.filter(id=user.id).exists():
            return True
            
        return False


class BotFileViewSet(viewsets.ViewSet):
    """
    API endpoint for managing bot-specific files via DARE backend.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated, HasBotAccess]
    parser_classes = (MultiPartParser, FormParser)

    def list(self, request, bot_id=None):
        """List all files associated with this bot from DARE backend"""
        try:
            bot = Bot.objects.get(id=bot_id)
            if not bot.dare_file_ids:
                return Response({'files': [], 'count': 0, 'debug': f'Bot {bot_id} has no file IDs'})
            
            # Get file details from DARE backend
            # Get JWT token from request.auth (returned by JWTAuthentication)
            user_token = request.auth
            if not user_token:
                raise ValidationError("User authentication token not available")
            
            file_details = []
            for file_id in bot.dare_file_ids:
                try:
                    file_info = files_client.get_file_by_id(file_id, user_token)
                    # Proxy DARE file format directly
                    proxied_file = convert_dare_file_to_bot_file(file_info)
                    file_details.append(proxied_file)
                except DareApiError as e:
                    # File may have been deleted from DARE, skip it
                    continue
                except Exception as e:
                    continue
            
            return Response({
                'files': file_details,
                'count': len(file_details)
            })
            
        except Bot.DoesNotExist:
            raise ValidationError("Bot not found")

    def create(self, request, bot_id=None):
        """Upload files to DARE backend and associate with bot"""
        try:
            bot = Bot.objects.get(id=bot_id)
            # Get JWT token from request.auth (returned by JWTAuthentication)
            user_token = request.auth
            if not user_token:
                raise ValidationError("User authentication token not available")
            
            files = request.FILES.getlist('files')
            if not files:
                raise ValidationError("No files provided")
            
            # Upload files to DARE backend
            # Get names array from frontend (if provided) or use file names as fallback
            names_from_frontend = request.data.getlist('names', [])
            # Use frontend names if provided and matches file count, otherwise fallback to filenames
            names_to_use = names_from_frontend if len(names_from_frontend) == len(files) else None
            
            # Determine chunk settings: request overrides user defaults
            try:
                req_chunk_size = request.data.get('chunk_size')
                req_overlap_size = request.data.get('overlap_size')
                chunk_size = int(req_chunk_size) if req_chunk_size is not None else getattr(request.user, 'chunk_size', 1000)
                overlap_size = int(req_overlap_size) if req_overlap_size is not None else getattr(request.user, 'overlap_size', 100)
            except (TypeError, ValueError):
                chunk_size = getattr(request.user, 'chunk_size', 1000)
                overlap_size = getattr(request.user, 'overlap_size', 100)

            upload_result = files_client.upload_files(
                files=files,
                user_token=user_token,
                names=names_to_use,
                tags=request.data.getlist('tags', []),
                chunk_size=chunk_size,
                overlap_size=overlap_size,
            )
            
            # DARE returns a list directly, not a dict with 'files' key
            if upload_result and isinstance(upload_result, list):
                new_file_ids = [f['id'] for f in upload_result]
                # Update bot's file IDs
                current_file_ids = bot.dare_file_ids or []
                updated_file_ids = list(set(current_file_ids + new_file_ids))
                bot.dare_file_ids = updated_file_ids
                bot.save()
                
                proxied_files = [convert_dare_file_to_bot_file(f) for f in upload_result]
                
                return Response({
                    'files': proxied_files,
                    'count': len(proxied_files),
                    'message': f'Files uploaded and associated with bot {bot_id}'
                }, status=status.HTTP_201_CREATED)
            
            return Response({'error': 'No files in upload result'}, status=status.HTTP_400_BAD_REQUEST)
            
        except Bot.DoesNotExist:
            raise ValidationError("Bot not found")
        except DareApiError as e:
            raise ValidationError(f"File upload failed: {str(e)}")

    def destroy(self, request, bot_id=None, pk=None):
        """Remove file association from bot and optionally delete from DARE"""
        try:
            bot = Bot.objects.get(id=bot_id)
            file_id = int(pk)
            
            # Remove file ID from bot's list
            if bot.dare_file_ids and file_id in bot.dare_file_ids:
                bot.dare_file_ids.remove(file_id)
                bot.save()
            
            # Optionally delete from DARE backend if requested
            if request.query_params.get('delete_from_dare') == 'true':
                user_token = getattr(request.user, 'dare_access_token', None)
                if user_token:
                    try:
                        files_client.delete_files([file_id], user_token)
                    except DareApiError:
                        # File might already be deleted, continue
                        pass
            
            return Response(status=status.HTTP_204_NO_CONTENT)
            
        except Bot.DoesNotExist:
            raise ValidationError("Bot not found")
        except ValueError:
            raise ValidationError("Invalid file ID")

    @action(detail=True, methods=['get'])
    def download(self, request, bot_id=None, pk=None):
        """Download file content from DARE backend"""
        try:
            bot = Bot.objects.get(id=bot_id)
            file_id = int(pk)
            
            if not bot.dare_file_ids or file_id not in bot.dare_file_ids:
                raise Http404("File not found")
            
            # Get JWT token from request.auth (returned by JWTAuthentication)
            user_token = request.auth
            if not user_token:
                raise ValidationError("User authentication token not available")
            
            # Get file content from DARE backend
            response = files_client.get_file_content(file_id, user_token)
            
            # Create Django response with file content
            django_response = FileResponse(
                response.iter_content(chunk_size=8192),
                content_type=response.headers.get('Content-Type', 'application/octet-stream')
            )
            
            # Set filename if available in headers
            if 'Content-Disposition' in response.headers:
                django_response['Content-Disposition'] = response.headers['Content-Disposition']
            
            return django_response
            
        except Bot.DoesNotExist:
            raise Http404("Bot not found")
        except ValueError:
            raise Http404("Invalid file ID")
        except DareApiError:
            raise Http404("File not found or access denied")


class SecureFileServeView(APIView):
    """
    Secure file serving endpoint that validates user access before serving files.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, file_id):
        """Serve file if user has access via any bot"""
        try:
            file_id = int(file_id)
            
            # Check if user has access to any bot that contains this file
            user_bots = Bot.objects.filter(user=request.user, dare_file_ids__contains=[file_id])
            
            # Also check collaborator access
            collaborative_bots = Bot.objects.filter(
                bot_group__collaborators=request.user,
                dare_file_ids__contains=[file_id]
            )
            
            if not user_bots.exists() and not collaborative_bots.exists():
                raise Http404("File not found or access denied")
            
            # Get JWT token from request.auth (returned by JWTAuthentication)
            user_token = request.auth
            if not user_token:
                raise ValidationError("User authentication token not available")
            
            # Get file content from DARE backend
            response = files_client.get_file_content(file_id, user_token)
            
            # Create Django response with file content
            django_response = FileResponse(
                response.iter_content(chunk_size=8192),
                content_type=response.headers.get('Content-Type', 'application/octet-stream')
            )
            
            # Set filename if available in headers
            if 'Content-Disposition' in response.headers:
                django_response['Content-Disposition'] = response.headers['Content-Disposition']
            
            return django_response
            
        except ValueError:
            raise Http404("Invalid file ID")
        except DareApiError:
            raise Http404("File not found or access denied")
