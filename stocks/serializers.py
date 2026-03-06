from rest_framework import serializers
from .models import Stock, News, Watchlist
from django.contrib.auth import get_user_model
from datetime import timedelta
from django.utils import timezone
from datetime import datetime

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['username', 'email', 'ai_credit']

class StockSerializer(serializers.ModelSerializer):
    """주식 목록 (리스트)에 사용될 간단한 Serializer"""
    class Meta:
        model = Stock
        fields = [
            'id', 'code', 'short_name', 'market', 'current_price', 'market_change', 'change_percent', 'volume', 'market_cap', 'price_to_book', 'forward_pe', 'sector', 'industry'
        ]


class WatchlistSerializer(serializers.ModelSerializer):
    stock = StockSerializer(read_only=True)
    stock_id = serializers.PrimaryKeyRelatedField(
        queryset=Stock.objects.all(),
        write_only=True,
        source='stock'
    )

    class Meta:
        model = Watchlist
        fields = ('id', 'stock', 'stock_id', 'target_price', 'created_at')
        read_only_fields = ('id', 'created_at', 'stock')

class StockSearchSerializer(StockSerializer):
    is_in_watchlist = serializers.SerializerMethodField()
    watchlist_id = serializers.SerializerMethodField()

    class Meta(StockSerializer.Meta):
        fields = StockSerializer.Meta.fields + ['is_in_watchlist', 'watchlist_id']

    def get_is_in_watchlist(self, obj):
        user = self.context.get('request').user
        if user and user.is_authenticated:
            # 미리 가져온 watchlist_stock_ids를 사용하지 않고 직접 쿼리
            return obj.watchlist_items.filter(user=user).exists()
        return False

    def get_watchlist_id(self, obj):
        user = self.context.get('request').user
        if user and user.is_authenticated:
            try:
                watchlist_item = obj.watchlist_items.get(user=user)
                return watchlist_item.pk
            except Watchlist.DoesNotExist:
                return None
        return None
    

class NewsSerializer(serializers.ModelSerializer):
    """뉴스 정보 직렬화를 위한 간단한 시리얼라이저"""
    class Meta:
        model = News
        fields = ('title', 'description', 'url', 'thumbnail', 'published_at', 'related_stocks') # url -> link 등 모델 필드명에 맞게 수정
        # 만약 모델에 'url' 필드가 있다면 'url'로 사용


class StockInfoSerializer(serializers.ModelSerializer):
    """주식의 'info' 부분만을 담당하는 상세 정보 시리얼라이저"""
    class Meta:
        model = Stock
        # 프론트엔드 StockInfo 모델에 필요한 모든 필드를 나열합니다.
        fields = (
            'id', 'code', 'short_name', 'long_name', 'market', 'is_sp500',
            'current_price', 'market_change', 'change_percent', 'day_high', 'day_low',
            'volume', 'market_cap', 'sector', 'industry', 'website',
            'long_business_summary', 'full_time_employees', 'trailing_pe',
            'forward_pe', 'price_to_book', 'dividend_yield',
            'fifty_two_week_high', 'fifty_two_week_low', 'city', 'state', 'country'
        )

# ⭐️ 최종적으로 프론트엔드에 응답을 보낼 메인 시리얼라이저 ⭐️
class StockDetailSerializer(serializers.ModelSerializer):
    """
    프론트엔드의 StockDetail 모델 구조에 맞춰
    주식 정보(info), 뉴스(news), 관심종목 정보(watchlist)를 한번에 반환합니다.
    """
    # 1. 중첩된 'info' 객체를 위해 별도의 시리얼라이저를 사용합니다.
    #    source='*'는 객체 전체(self)를 StockInfoSerializer에 전달하라는 의미입니다.
    info = StockInfoSerializer(source='*', read_only=True)

    # 2. 'news' 리스트를 위해 SerializerMethodField를 사용합니다.
    news = serializers.SerializerMethodField()
    stock_id = serializers.IntegerField(source='id', read_only=True)

    # 3. 'watchlist' 관련 정보를 위해 SerializerMethodField를 사용합니다.
    is_in_watchlist = serializers.SerializerMethodField()
    watchlist_id = serializers.SerializerMethodField()
    
    # stock_id는 info 필드 내의 'id'와 동일하므로 별도 필드는 불필요합니다.
    # 프론트엔드에서 info.id를 사용하면 됩니다.

    class Meta:
        model = Stock
        # 최종적으로 프론트엔드에 보낼 최상위 key들을 지정합니다.
        fields = ('info', 'news', 'stock_id', 'is_in_watchlist', 'watchlist_id')

    def get_news(self, obj):
        from .services import get_yfinance_stock_news
        """
        해당 주식(obj)과 관련된 뉴스를 반환합니다.
        1. DB에 1시간 이내의 최신 뉴스가 있는지 확인합니다.
        2. 있으면 DB 데이터를 반환합니다.
        3. 없으면 yfinance에서 새로 가져와 DB에 저장 후 반환합니다.
        """
        # 1. DB에서 1시간 이내에 생성된 최신 뉴스가 있는지 확인
        time_threshold = timezone.now() - timedelta(hours=24)
        # News 모델의 related_name이 'news'이므로 obj.news.all() 사용 가능
        recent_news = obj.news.filter(published_at__gte=time_threshold).order_by('-published_at')

        # 2. 유효한 최신 뉴스가 DB에 있으면 바로 반환
        if recent_news.exists() and len(recent_news) > 9:
            print(f"✅ DB 캐시 히트: {obj.code}의 뉴스를 DB에서 반환합니다.")
            serializer = NewsSerializer(recent_news, many=True)
            return serializer.data

        # 3. DB에 뉴스가 없거나 오래되었으면, yfinance API 호출
        print(f"🔥 DB 캐시 미스: {obj.code}의 뉴스를 yfinance에서 가져옵니다.")
        news_from_api = get_yfinance_stock_news(obj.code)
        
        if not news_from_api:
            # API에서도 뉴스를 가져오지 못했다면 빈 리스트 반환
            return []

        # 4. 가져온 뉴스를 DB에 저장 (기존 뉴스는 삭제하여 최신 상태 유지)
        
        # (선택적) 이 주식과 관련된 기존의 모든 뉴스를 삭제
        # obj.news.clear()
        news_instances = [] # 생성 또는 업데이트된 News 객체들을 담을 리스트

        for news_item in news_from_api:
            # yfinance는 Unix 타임스탬프(초 단위)로 날짜를 반환하므로 datetime 객체로 변환
            pub_datetime = news_item['pub_date']
            try:
                # ISO 8601 형식의 문자열 ('Z'는 UTC를 의미)을 timezone-aware datetime 객체로 변환
                # .replace('Z', '+00:00')는 모든 파이썬 버전에서 호환성을 보장합니다.
                pub_datetime_obj = datetime.fromisoformat(pub_datetime.replace('Z', '+00:00'))
            except (ValueError, TypeError):
                # 날짜 형식이 잘못되었거나 값이 없는 경우, 현재 시간을 기본값으로 사용하거나 건너뜁니다.
                # 여기서는 해당 뉴스를 건너뛰는 것으로 처리합니다.
                print(f"⚠️ 잘못된 날짜 형식으로 뉴스 건너뜀: {pub_datetime}")
                continue

            # News 객체를 생성하되, 아직 DB에는 저장하지 않음 (bulk_create를 위해)
            # update_or_create를 사용하여 중복 방지 (url 기준)
            news_obj, created = News.objects.update_or_create(
                url=news_item['url'],
                defaults={
                    'title': news_item['title'],
                    'description': news_item['description'],
                    'thumbnail': news_item.get('thumbnail', ''),
                    'published_at': pub_datetime_obj, # <-- 변환된 datetime 객체 사용
                }
            )
            # 생성/업데이트된 News 객체와 현재 주식(Stock)을 연결
            news_instances.append(news_obj)

        if news_instances:
            obj.news.set(news_instances)
        # 5. 새로 생성/업데이트된 뉴스 데이터를 직렬화하여 반환
        serializer = NewsSerializer(news_instances, many=True)
        return serializer.data

    def get_is_in_watchlist(self, obj):
        """요청을 보낸 사용자가 이 주식을 관심종목에 추가했는지 여부를 반환합니다."""
        user = self.context.get('request').user
        if user and user.is_authenticated:
            # 가정: Watchlist 모델에 'stock'과 'user' ForeignKey 필드가 있음
            return Watchlist.objects.filter(stock=obj, user=user).exists()
        return False

    def get_watchlist_id(self, obj):
        """관심종목에 추가되었다면, 해당 Watchlist 아이템의 id(pk)를 반환합니다."""
        user = self.context.get('request').user
        if user and user.is_authenticated:
            item = Watchlist.objects.filter(stock=obj, user=user).first()
            return item.pk if item else None
        return None
    