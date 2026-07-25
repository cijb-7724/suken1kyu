更新
```
source .venv/bin/activate

python3 scripts/update_site.py --render
quarto preview

git status
git add .
git commit -m "Update site content"
git push origin main

quarto publish gh-pages --no-render
```
