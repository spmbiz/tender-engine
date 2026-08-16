import json
import sys
from pathlib import Path

import duckdb

from pipeline import materialize_fr_decp_awards as decp


def test_materializer_separates_awards_and_supplier_links(tmp_path, monkeypatch):
    source = tmp_path / "fixture.parquet"
    con = duckdb.connect()
    con.execute("""
      COPY (
        SELECT * FROM (VALUES
          ('B1:M1','M1','B1','Buyer One','Website maintenance','72413000','open',120000.0,12,DATE '2026-01-10',TIMESTAMP '2026-01-12 00:00:00',true,'S1','Supplier A','SIRET','0'),
          ('B1:M2','M2','B1','Buyer One','Printing','79810000','open',50000.0,6,DATE '2026-02-10',TIMESTAMP '2026-02-12 00:00:00',true,'S2','Supplier B','SIRET','0'),
          ('B1:M2','M2','B1','Buyer One','Printing','79810000','open',55000.0,6,DATE '2026-03-10',TIMESTAMP '2026-03-12 00:00:00',false,'S3','Old Supplier','SIRET','1')
        ) AS t(uid,id,acheteur_id,acheteur_nom,objet,codeCPV,procedure,montant,dureeMois,dateNotification,datePublicationDonnees,donneesActuelles,titulaire_id,titulaire_nom,titulaire_typeIdentifiant,modification_id)
      ) TO ? (FORMAT PARQUET)
    """, [str(source)])
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["decp", "--source-path", str(source), "--output", str(out)])
    decp.main()

    stats = json.loads((out / "stats.json").read_text())
    assert stats["counts"]["awards"] == 2
    assert stats["counts"]["award_supplier_links"] == 2
    assert stats["counts"]["buyer_supplier_priors"] == 2

    awards = duckdb.sql(f"SELECT grain, award_id FROM read_parquet('{out / 'awards.parquet'}') ORDER BY award_id").fetchall()
    assert awards == [("AWARD", "B1:M1"), ("AWARD", "B1:M2")]
    links = duckdb.sql(f"SELECT supplier_id FROM read_parquet('{out / 'award_supplier_links.parquet'}') ORDER BY supplier_id").fetchall()
    assert links == [("S1",), ("S2",)]
