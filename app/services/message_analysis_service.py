import re
import logging
from typing import List, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.schemas.workflow import MessageAnalysisResult, MessageAnalysisRule

logger = logging.getLogger(__name__)

class MessageAnalysisService:
    """Service for analyzing message content to trigger workflow automations"""
    
    # Default keywords for common categories (used as fallback when no custom categories exist)
    DEFAULT_CATEGORY_KEYWORDS = {
        'support': ['help', 'assistance', 'support', 'problema', 'issue', 'trouble', 'error', 'bug', 'ayuda'],
        'billing': ['payment', 'bill', 'invoice', 'charge', 'cost', 'price', 'refund', 'factura', 'pago', 'cobro'],
        'technical': ['technical', 'system', 'server', 'database', 'api', 'integration', 'técnico', 'sistema'],
        'complaint': ['complain', 'angry', 'disappointed', 'terrible', 'awful', 'worst', 'horrible', 'mal servicio', 'quejas'],
        'praise': ['excellent', 'great', 'amazing', 'wonderful', 'fantastic', 'love', 'perfect', 'excelente', 'genial']
    }
    
    # Urgency keywords
    URGENCY_KEYWORDS = {
        'high': ['urgent', 'emergency', 'critical', 'asap', 'immediately', 'urgente', 'emergencia', 'crítico'],
        'medium': ['soon', 'important', 'needed', 'pronto', 'importante', 'necesario'],
        'low': ['when possible', 'whenever', 'later', 'cuando sea posible', 'más tarde']
    }
    
    # Simple sentiment keywords (basic implementation)
    POSITIVE_WORDS = ['good', 'great', 'excellent', 'happy', 'satisfied', 'love', 'perfect', 'bueno', 'excelente', 'feliz']
    NEGATIVE_WORDS = ['bad', 'terrible', 'awful', 'hate', 'angry', 'disappointed', 'worst', 'malo', 'terrible', 'odio']
    
    @classmethod
    async def analyze_message(cls, message_content: str, custom_rules: Optional[MessageAnalysisRule] = None, db: AsyncSession = None, workspace_id: int = None) -> MessageAnalysisResult:
        """
        Analyze message content and return analysis results
        """
        try:
            if not message_content or not isinstance(message_content, str):
                return cls._default_analysis_result()
                
            message_lower = message_content.lower().strip()
            
            # Sentiment analysis (basic keyword-based)
            sentiment = cls._analyze_sentiment(message_lower)
            
            # Urgency analysis
            urgency_level = cls._analyze_urgency(message_lower)
            
            # Category detection (using real workspace categories)
            categories = await cls._detect_categories(message_lower, db, workspace_id)
            
            # Keywords detection
            keywords_found = cls._find_keywords(message_lower, custom_rules)
            
            # Language detection (very basic)
            language = cls._detect_language(message_lower)
            
            # Calculate confidence based on how many indicators we found
            confidence = cls._calculate_confidence(sentiment, urgency_level, categories, keywords_found)
            
            return MessageAnalysisResult(
                sentiment=sentiment,
                urgency_level=urgency_level,
                keywords_found=keywords_found,
                categories=categories,
                language=language,
                confidence=confidence
            )
            
        except Exception as e:
            logger.error(f"Error analyzing message: {str(e)}")
            return cls._default_analysis_result()
    
    @classmethod
    def _analyze_sentiment(cls, message: str) -> float:
        """Simple sentiment analysis using keyword counting"""
        positive_count = sum(1 for word in cls.POSITIVE_WORDS if word in message)
        negative_count = sum(1 for word in cls.NEGATIVE_WORDS if word in message)
        
        total_sentiment_words = positive_count + negative_count
        if total_sentiment_words == 0:
            return 0.0  # Neutral
            
        # Scale from -1 to 1
        sentiment_score = (positive_count - negative_count) / total_sentiment_words
        return max(-1.0, min(1.0, sentiment_score))
    
    @classmethod
    def _analyze_urgency(cls, message: str) -> str:
        """Detect urgency level in message"""
        for level, keywords in cls.URGENCY_KEYWORDS.items():
            if any(keyword in message for keyword in keywords):
                return level
        return 'low'
    
    @classmethod
    async def _detect_categories(cls, message: str, db: AsyncSession, workspace_id: int) -> List[str]:
        """Detect categories mentioned in the message using real workspace categories"""
        categories = []
        
        if db and workspace_id:
            try:
                from app.models.category import Category
                
                result = await db.execute(
                    select(Category).filter(Category.workspace_id == workspace_id)
                )
                workspace_categories = result.scalars().all()
                
                for category in workspace_categories:
                    category_name = category.name.lower()
                    if category_name in message:
                        categories.append(category.name)
                        
                for category, keywords in cls.DEFAULT_CATEGORY_KEYWORDS.items():
                    if any(keyword in message for keyword in keywords):
                        if category not in [cat.lower() for cat in categories]:
                            categories.append(category)
                            
            except Exception as e:
                logger.error(f"Error querying workspace categories: {str(e)}")
                for category, keywords in cls.DEFAULT_CATEGORY_KEYWORDS.items():
                    if any(keyword in message for keyword in keywords):
                        categories.append(category)
        else:
            for category, keywords in cls.DEFAULT_CATEGORY_KEYWORDS.items():
                if any(keyword in message for keyword in keywords):
                    categories.append(category)
                    
        return categories
    
    @classmethod
    def _find_keywords(cls, message: str, custom_rules: Optional[MessageAnalysisRule]) -> List[str]:
        """Find keywords in message based on custom rules"""
        keywords_found = []
        
        if custom_rules and custom_rules.keywords:
            for keyword in custom_rules.keywords:
                if keyword.lower() in message:
                    keywords_found.append(keyword)
                    
        # Exclude keywords if specified
        if custom_rules and custom_rules.exclude_keywords:
            keywords_found = [kw for kw in keywords_found 
                            if not any(excl.lower() in kw.lower() for excl in custom_rules.exclude_keywords)]
                            
        return keywords_found
    
    @classmethod
    def _detect_language(cls, message: str) -> str:
        """Basic language detection"""
        spanish_indicators = ['el', 'la', 'de', 'que', 'y', 'en', 'un', 'es', 'se', 'no', 'te', 'lo', 'le', 'da', 'su', 'por', 'son', 'con', 'para', 'está', 'como', 'pero', 'muy', 'más']
        english_indicators = ['the', 'and', 'of', 'to', 'a', 'in', 'is', 'it', 'you', 'that', 'he', 'was', 'for', 'on', 'are', 'as', 'with', 'his', 'they', 'at', 'be', 'this', 'have', 'from', 'or', 'one', 'had', 'by', 'word', 'but', 'not', 'what', 'all', 'were', 'we', 'when']
        
        spanish_count = sum(1 for word in spanish_indicators if f' {word} ' in f' {message} ')
        english_count = sum(1 for word in english_indicators if f' {word} ' in f' {message} ')
        
        if spanish_count > english_count:
            return 'es'
        elif english_count > spanish_count:
            return 'en'
        else:
            return 'unknown'
    
    @classmethod
    def _calculate_confidence(cls, sentiment: float, urgency: str, categories: List[str], keywords: List[str]) -> float:
        """Calculate confidence score based on analysis results"""
        confidence = 0.5  # Base confidence
        
        # Increase confidence if we detected sentiment
        if abs(sentiment) > 0.1:
            confidence += 0.2
            
        # Increase confidence if we detected urgency
        if urgency != 'low':
            confidence += 0.1
            
        # Increase confidence based on categories found
        confidence += min(0.2, len(categories) * 0.1)
        
        # Increase confidence based on keywords found
        confidence += min(0.1, len(keywords) * 0.05)
        
        return min(1.0, confidence)
    
    @classmethod
    def _default_analysis_result(cls) -> MessageAnalysisResult:
        """Return default analysis result for error cases"""
        return MessageAnalysisResult(
            sentiment=0.0,
            urgency_level='low',
            keywords_found=[],
            categories=[],
            language='unknown',
            confidence=0.0
        )
    
    @classmethod
    async def check_trigger_match(cls, analysis: MessageAnalysisResult, trigger: str, rules: Optional[MessageAnalysisRule] = None, db: AsyncSession = None, workspace_id: int = None) -> bool:
        """
        Check if the analysis results match the workflow trigger
        """
        try:
            if trigger == 'message.contains_keywords':
                return len(analysis.keywords_found) > 0
                
            elif trigger == 'message.sentiment_negative':
                threshold = rules.sentiment_threshold if rules and rules.sentiment_threshold is not None else -0.1
                return analysis.sentiment < threshold
                
            elif trigger == 'message.sentiment_positive':
                threshold = rules.sentiment_threshold if rules and rules.sentiment_threshold is not None else 0.1
                return analysis.sentiment > threshold
                
            elif trigger == 'message.urgency_high':
                return analysis.urgency_level == 'high'
                
            elif trigger == 'message.urgency_medium':
                return analysis.urgency_level in ['high', 'medium']
                
            elif trigger == 'message.language_detected':
                return rules and rules.language and analysis.language == rules.language
                
            elif trigger.startswith('message.category_'):
                if trigger.startswith('message.category_custom_'):
                    safe_name = trigger.replace('message.category_custom_', '')
                    
                    if db and workspace_id:
                        try:
                            from app.models.category import Category
                            result = await db.execute(
                                select(Category).filter(Category.workspace_id == workspace_id)
                            )
                            workspace_categories = result.scalars().all()
                            
                            for category in workspace_categories:
                                category_safe_name = category.name.lower().replace(' ', '_').replace('-', '_')
                                category_safe_name = ''.join(c for c in category_safe_name if c.isalnum() or c == '_')
                                
                                if category_safe_name == safe_name:
                                    return category.name in analysis.categories
                                    
                        except Exception as e:
                            logger.error(f"Error checking custom category trigger: {str(e)}")
                            return False
                else:
                    category = trigger.replace('message.category_', '')
                    return category in analysis.categories
                
            elif not trigger.startswith('message.'):
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"Error checking trigger match: {str(e)}")
            return False
