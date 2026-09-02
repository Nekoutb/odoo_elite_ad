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

    SERVICE_TYPES = {
        'IM': ("Import", 10,
               ['BL', 'INV', 'PKL', 'DI', 'RVC', 'BESC', 'ANOR', 'LFAC',
                'CAH', 'DFIS']),
        'BO': ("Export Bois", 20,
               ['OBOK', 'OTRA', 'INV', 'ECH', 'DOMX', 'DEXP', 'SPEC', 'BCMD']),
        'ES': ("Export Standard", 30,
               ['OTRA', 'INV', 'PKL', 'ECH', 'BCMD']),
        'AI': ("Aérien", 40,
               ['LTA', 'INV', 'PKL', 'FTRA', 'DI', 'RVC', 'ANOR', 'VTEC',
                'FTEC', 'EUR1', 'CANA']),
    }
    Service = env['logistics.service.type']
    Line = env['logistics.service.type.document']
    for code, (name, seq, doc_codes) in SERVICE_TYPES.items():
        st = Service.search([('code', '=', code),
                             ('company_id', '=', company.id)], limit=1)
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
