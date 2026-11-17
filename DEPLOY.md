# Git & Deployment Commands

## Push Changes to GitHub (Windows PowerShell)
```powershell
git add .; git commit -m "Update app"; git push

## Deploy Latest Changes on Docker Host
cd /config/berserker-tracker
git fetch origin main
git reset --hard origin/main
docker-compose down
docker-compose build --no-cache
docker-compose up -d
