# DCE rollback A/B benchmark

This benchmark compares the pre-V14 production snapshot `112c62fe6a77c3b8c3295ca48bb151366e363d71` with the current resolver on the exact same 20 candidate records recovered from durable DCE release `dce-harvest-32081860247`.

The fixed ID set intentionally mixes fast and slow PLACSP cases, direct Greek KHMDHS attachments, Public Contracts Scotland alias routing, South Africa generic public pages, Germany DOE, Doffin and SIMAP. The comparison fails closed if the current resolver loses a previously downloaded public DCE, introduces an unwired/broken status, loses a successful return code, or drops a manifest/result. Latency changes and changed download hashes are reported separately because live procurement endpoints can change between the two sequential probes.

Every resolver iteration should run both the rollback A/B job and the independent expansion-live job before merging.
