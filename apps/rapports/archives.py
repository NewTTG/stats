"""Les exports immédiats sont conservés comme les rapports du worker."""
from django.core.files.base import ContentFile
from django.utils import timezone

from .models import Rapport


def archiver_export(user, req, contenu, demande):
    rapport = Rapport(utilisateur=user, titre=f'Export Excel · {", ".join(req.perimetre.valeurs) or "réseau"}'[:200],
                      nature='requete', format='xlsx', parametres={'requete': req.model_dump(mode='json')},
                      demande=demande, statut='termine', termine_le=timezone.now())
    rapport.fichier.save(f'kpi_{req.periode.debut:%Y%m%d}_{req.periode.fin:%Y%m%d}.xlsx', ContentFile(contenu), save=False)
    rapport.save()
    return rapport
