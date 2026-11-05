# notes/views.py
from rest_framework import viewsets, permissions, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Note
from .serializers import NoteSerializer
from users.authentication import JWTAuthentication
from bots.models import Bot
from access_codes.models import SubscriptionCodeAcceptance

class NoteViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing bot-specific notes.
    Users can only access notes for bots they have access to.
    """
    serializer_class = NoteSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'public_id'

    def _user_has_access_to_bot(self, user, bot):
        """Check if user has access to bot via access codes or ownership"""
        # Check if user is the bot owner
        if bot.user == user:
            return True
            
        # Check if user is the bot group owner
        if bot.bot_group.owner == user:
            return True
            
        # Check if user has redeemed an access code for this bot
        has_access_code = SubscriptionCodeAcceptance.objects.filter(
            user=user,
            subscription_code__bot=bot
        ).exists()
        
        return has_access_code

    def get_queryset(self):
        """Return notes for bots the current user has access to"""
        user = self.request.user
        bot_id = self.request.query_params.get('bot_id')

        if bot_id:
            try:
                bot = Bot.objects.get(id=bot_id)
                if self._user_has_access_to_bot(user, bot):
                    return Note.objects.filter(bot=bot)
                else:
                    return Note.objects.none()
            except Bot.DoesNotExist:
                return Note.objects.none()

        accessible_bots = []
        for bot in Bot.objects.all():
            if self._user_has_access_to_bot(user, bot):
                accessible_bots.append(bot.id)
        
        return Note.objects.filter(bot_id__in=accessible_bots)

    def perform_create(self, serializer):
        """Create a note for a specific bot"""
        bot_id = self.request.data.get('bot_id')
        
        if not bot_id:
            raise serializers.ValidationError({'bot_id': 'This field is required.'})

        try:
            bot = Bot.objects.get(id=bot_id)
            
            if not self._user_has_access_to_bot(self.request.user, bot):
                raise serializers.ValidationError({'bot_id': 'Access denied to this bot.'})
                
        except Bot.DoesNotExist:
            raise serializers.ValidationError({'bot_id': 'No Bot matches the given query.'})
        
        serializer.save(bot=bot, user=self.request.user)

    @action(detail=False, methods=['get'])
    def by_bot(self, request):
        """Get all notes for a specific bot"""
        bot_id = request.query_params.get('bot_id')
        if not bot_id:
            return Response(
                {'error': 'bot_id parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            bot = Bot.objects.get(id=bot_id)
            if not self._user_has_access_to_bot(request.user, bot):
                return Response(
                    {'error': 'Access denied to this bot'},
                    status=status.HTTP_403_FORBIDDEN
                )
                
            notes = Note.objects.filter(bot=bot)
            serializer = self.get_serializer(notes, many=True)
            return Response(serializer.data)
        except Bot.DoesNotExist:
            return Response(
                {'error': 'Bot not found or access denied'},
                status=status.HTTP_404_NOT_FOUND
            )

