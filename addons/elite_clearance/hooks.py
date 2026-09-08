def seed_clearance_master_data(env):
    """Seed Elite Advisors' real service types, document checklists and
    expense categories. Create-if-missing by code, so it is safe on fresh
    installs AND on databases that already carry demo or manual records."""
    company = env.company

    DOC_TYPES = [
        ('BL', "BL (Bill of Lading)"),
        ('INV', "Facture commerciale (Invoice)"),
        ('PKL', "Packing List"),
        ('DI', "Déclaration d'Importation (DI)"),
        ('RVC', "Rapport sur la Valeur et le Classement tarifaire (RVC)"),
        ('BESC', "Bordereau Électronique de Suivi des Cargaisons (BESC)"),
        ('ANOR', "Attestation de Conformité (ANOR)"),
        ('LFAC', "Lettre de facilité"),
        ('CAH', "Certificat d'Assurance (CAH)"),
        ('DFIS', "Dossier fiscal"),
        ('OBOK', "Ordre de booking"),
        ('OTRA', "Ordre de transit"),
        ('ECH', "Engagement de change"),
        ('DOMX', "Domiciliation d'exportation"),
        ('DEXP', "Déclaration d'exploitation"),
        ('SPEC', "Spécifications"),
        ('BCMD', "Bon de commande"),
        ('LTA', "LTA (Lettre de Transport Aérien)"),
        ('FTRA', "Facture transport"),
        ('VTEC', "Visa technique"),
        ('FTEC', "Fiche technique"),
        ('EUR1', "EUR 1"),
        ('CANA', "Certificat d'analyse"),
    ]
    Doc = env['logistics.document.type']
    docs = {}
    for seq, (code, name) in enumerate(DOC_TYPES, start=1):
        rec = Doc.search([('code', '=', code),
                          ('company_id', '=', company.id)], limit=1)
        if not rec:
            rec = Doc.create({'code': code, 'name': name, 'sequence': seq * 10})
        docs[code] = rec

    # The four services Elimelec sells (owner spec, 08/09/2026). The CODES
    # are load-bearing - file and invoice references are built from them
    # (2026IM0009, EL26IM0001) and sit on posted moves - so a service is
    # renamed, never recoded. "Export Bois" is retired rather than deleted,
    # for the same reason: old files still point at it.
    SERVICE_TYPES = {
        'IM': ("Import Maritime", 10,
               ['BL', 'INV', 'PKL', 'DI', 'RVC', 'BESC', 'ANOR', 'LFAC',
                'CAH', 'DFIS']),
        'ES': ("Export", 20,
               ['OTRA', 'INV', 'PKL', 'ECH', 'BCMD']),
        'AI': ("Aérien (Air Freight)", 30,
               ['LTA', 'INV', 'PKL', 'FTRA', 'DI', 'RVC', 'ANOR', 'VTEC',
                'FTEC', 'EUR1', 'CANA']),
        'TR': ("Transport", 40, ['OTRA', 'INV', 'BCMD']),
    }
    # What each was called when we seeded it. A service is renamed only if
    # it still carries that name: if the owner has renamed it themselves,
    # theirs wins.
    RENAMED = {'IM': "Import", 'ES': "Export Standard", 'AI': "Aérien"}
    RETIRED = {'BO': "Export Bois"}
    # The ports a file is opened against. Port is required at creation
    # and offers no "create" entry, and only a Clearance Manager may add
    # one - so with none seeded, nobody could open a file at all on a
    # database that has never run the Teese import (found by review,
    # 08/09/2026). Matched on NAME, which is the model's unique key: the
    # importer creates ports name-only, so keying on code would try to
    # insert a second "Douala". There is no company_id on a port - it is
    # geography, not an accounting entity.
    PORTS = [
        ("DLA", "Douala", "Douala"),
        ("KRB", "Kribi", "Kribi"),
        ("TKO", "Tiko", "Tiko"),
        ("LMB", "Limbe", "Limbe"),
        ("DLA-AIR", "Douala Airport", "Douala"),
        ("NSI", "Yaoundé Nsimalen Airport", "Yaoundé"),
    ]
    Port = env['logistics.port']
    by_name = {p.name.strip().upper(): p
               for p in Port.with_context(active_test=False).search([])}
    for seq, (code, name, city) in enumerate(PORTS, start=1):
        existing = by_name.get(name.upper())
        if not existing:
            Port.create({'name': name, 'code': code, 'city': city,
                         'sequence': seq * 10})
        elif not existing.code:
            existing.code = code       # back-fill an imported row, never rename

    Service = env['logistics.service.type']
    Line = env['logistics.service.type.document']
    for code, was in RETIRED.items():
        old = Service.with_context(active_test=False).search(
            [('code', '=', code), ('company_id', '=', company.id)], limit=1)
        if old and old.active and old.name == was:
            old.active = False
    for code, (name, seq, doc_codes) in SERVICE_TYPES.items():
        st = Service.search([('code', '=', code),
                             ('company_id', '=', company.id)], limit=1)
        if st and st.name == RENAMED.get(code):
            st.name = name
        if not st:
            st = Service.create({'code': code, 'name': name, 'sequence': seq,
                                 'commission_rate': 2.0})
        for i, dc in enumerate(doc_codes, start=1):
            if not Line.search([('service_type_id', '=', st.id),
                                ('document_type_id', '=', docs[dc].id)], limit=1):
                Line.create({'service_type_id': st.id,
                             'document_type_id': docs[dc].id,
                             'is_mandatory': True, 'sequence': i * 10})

    CATEGORIES = [
        ('FBL', "Frais de BL"),
        ('FRET', "Facture fret"),
        ('TIMB', "Timbre"),
        ('TELS', "Téléphone secrétariat"),
        ('TELD', "Téléphone douane (TEL Douane)"),
        ('DILD', "Diligences douane"),
        ('DDDI', "Diligence de défaut de DI"),
        ('TDRY', "Transport Dry"),
        ('TCON', "Transport conventionnel"),
        ('TLIV', "Transport livraison"),
        ('PESC', "Pesée conteneur"),
        ('RTC', "RTC Acconage & relevage"),
        ('RVID', "Retour vide"),
        ('MANU', "Manutention"),
        ('MAGA', "Frais de magasinage"),
        ('PAD', "Redevances PAD"),
        ('PHYT', "Frais phytosanitaires"),
        ('VSAN', "Visa santé"),
        ('LEGH', "Légalisation engagement sur l'honneur"),
        ('XLEG', "Frais extra-légaux"),
        ('ASSL', "Assurance locale"),
    ]
    Cat = env['logistics.expense.category']
    for seq, (code, name) in enumerate(CATEGORIES, start=1):
        if not Cat.search([('code', '=', code),
                           ('company_id', '=', company.id)], limit=1):
            Cat.create({'code': code, 'name': name, 'sequence': seq * 10})
