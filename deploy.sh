#!/bin/bash
# BookIPS 배포 스크립트
# 사용법: ./deploy.sh
#
# 사전 준비: .env 파일에 키가 설정되어 있어야 합니다.

set -e

cd "$(dirname "$0")"

# .env 파일에서 환경변수 로드
if [ ! -f .env ]; then
    echo "❌ .env 파일이 없습니다. .env.example을 복사해서 키를 입력하세요."
    exit 1
fi

source .env

echo "📚 BookIPS 배포 시작..."
git pull

gcloud run deploy bookips \
  --source . \
  --region asia-northeast3 \
  --allow-unauthenticated \
  --set-env-vars="NL_API_KEY=${NL_API_KEY},GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID},GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET},SECRET_KEY=${SECRET_KEY},GOOGLE_REDIRECT_URI=${GOOGLE_REDIRECT_URI},NAVER_CLIENT_ID=${NAVER_CLIENT_ID},NAVER_CLIENT_SECRET=${NAVER_CLIENT_SECRET}"

echo "✅ 배포 완료!"
echo "🌐 https://bookips-867241382288.asia-northeast3.run.app"
