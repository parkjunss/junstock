from stocks.models import Stock
def user_stocks(request):
    if request.user.is_authenticated:
        # 사용자가 등록한 Watchlist와 연결된 Stock들만 필터링
        return {'my_stocks': Stock.objects.filter(watchlist_items__user=request.user)}
    return {'my_stocks': []}