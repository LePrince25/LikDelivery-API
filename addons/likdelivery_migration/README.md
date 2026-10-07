# likdelivery_migration — Import one-shot de la référence Flask (SQLite)

Module ETL **one-shot** (pas une API) qui importe les données de la base
SQLite de référence (`main/instance/livraison.db`) dans `likdelivery_core`.

## Pré-requis : copier le fichier SQLite dans le conteneur

Le conteneur `web` ne voit pas le système de fichiers de l'hôte hors volumes.
Le chemin lu par le module est celui **dans le conteneur** (paramètre
`ir.config_parameter` `likdelivery_migration.sqlite_path`, défaut
`/var/lib/odoo/livraison.db`). `/var/lib/odoo` est un volume nommé
(`likdelivery-odoo-data`) — le plus simple est `docker cp` :

```bash
cd /Users/leprince/dev/delivery-/delivery
docker cp /chemin/vers/livraison.db "$(docker compose ps -q web)":/var/lib/odoo/livraison.db
```

(Alternative : déposer le fichier dans `delivery/config/` — monté sur
`/etc/odoo` — et renseigner le chemin `/etc/odoo/livraison.db` dans le
champ « Chemin SQLite » de l'assistant.)

## Installation

```bash
cd /Users/leprince/dev/delivery-/delivery
docker compose stop web
docker compose run --rm --no-deps --entrypoint odoo web \
    -d db-likdelivery -i likdelivery_migration --stop-after-init --no-http
docker compose start web
```

## Lancer l'import

Via l'UI : menu **Livraison → Migration → Imports**, créer un enregistrement,
bouton **« Lancer l'import »**. Le rapport de réconciliation s'affiche dans le
champ « Rapport ».

Via `odoo shell` (recommandé pour les gros volumes — pas de timeout HTTP) :

```bash
docker compose exec -T web odoo shell -d db-likdelivery --no-http <<'EOF'
rec = env["likdelivery.migration.import"].create({"name": "Import initial"})
rec.action_run_import()
env.cr.commit()
print(rec.report)
EOF
```

## Propriétés

- **Pas de préservation d'IDs** : chaque enregistrement reçoit un nouvel id
  Odoo ; la correspondance est stockée dans `likdelivery.migration.map`
  (`entity`, `old_id` → `new_id`, unique(entity, old_id)). Toutes les FKs
  sont remappées via cette table.
- **Idempotent** : relancer l'import ne duplique rien — les `old_id` déjà
  mappés sont sautés.
- **Déduplication avec les données démo** : utilisateurs matchés par `phone`,
  catégories par `name`, liens boutique/flotte par (parent, livreur),
  commandes/courses colis par `code`, transactions par `reference` — la
  correspondance est enregistrée sans créer de doublon.
- **Mots de passe** : hash pbkdf2:sha256 copié **verbatim** dans
  `likdelivery.user.lik_password_hash` (reste valide) ; `lik_jwt_jti` vide.
- **Savepoints** : un par entité + un par ligne — une ligne ou une entité en
  échec n'avorte pas le reste ; les erreurs sont listées dans le rapport.
- **Ordre d'import** : catégories → utilisateurs → horaires → produits →
  liens boutique/flotte → commandes (+lignes) → courses → paniers → courses
  colis → règles d'annulation → transactions → notifications → positions GPS
  → journaux d'audit → retraits.

## Rapport de réconciliation

Écrit sur l'enregistrement (`report`) + logs Odoo. Contient :
- compteurs par entité (SQLite / créés / réutilisés / sautés / présents Odoo / erreurs) ;
- Σ `orders.total`, Σ `delivery_runs.price`, Σ `wallet_withdrawals.amount` des deux côtés ;
- unicité des codes commandes, courses colis, références de paiement ;
- égalité des portefeuilles recalculés par utilisateur (données migrées
  uniquement) : earned = Σ runs livrées (livreur) / Σ product_total livrés
  (fournisseur), dispo = max(0, round(earned − retraits completed+pending, 0)).

## Limites connues

- Les comptes `res.users` back-office ne sont **pas** créés (admins compris) :
  seuls `res.partner` + `likdelivery.user` sont migrés.
- Les horodatages `created_at` hérités ne sont pas portés (`create_date`
  Odoo non inscriptible). Exceptions : `driver_location.recorded_at` est
  préservé ; `audit_log.details` reçoit le timestamp d'origine.
- `audit_log.target_id` reste dans l'espace d'IDs hérité (colonne Integer
  brute, comme la référence).
- `users.balance` n'est pas porté : le portefeuille Odoo est dérivé.
- `id_document` / `cfe_document` (fichiers) ne sont pas migrés : la référence
  stocke des chemins locaux.
