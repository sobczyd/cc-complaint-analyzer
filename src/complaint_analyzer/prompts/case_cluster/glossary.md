## Nurse Call context and glossary

Sources: `nursecall-AGENTS.md`; Jama project CWS (Nurse Call - Parent Repository), components Design
Documents (CWS-CMP-122) and Software Design Documents (CWS-CMP-320); terms observed in the case summaries.
Expansions marked (unconfirmed) are inferred from usage, not from a Jama definition. Treat this section as
rules for grouping: use it to recognize that different wording can describe the same thing.

### Product overview
- Nurse Call (generic name) is the Baxter/Hillrom hospital nurse-call and clinical-alerting platform; the formal
  product name is Voalte Nurse Call (earlier NaviCare Nurse Call). Complaint code "CareComm - Nurse Call".
- Patient-room call buttons and room devices raise calls and alerts; an enterprise/unit server routes them to
  consoles, staff phones/mobile devices (Voalte, Vocera), and the Status Board. Audit and reporting record activity.
- Next-gen Nurse Call (NGNC) is a Postgres/Go/C# rewrite; most cases concern the installed Duplo/RCB/GRS generation.
- Generic-to-formal names: Nurse Call = Voalte Nurse Call; Status Board = Voalte Status Board; Admin Client =
  Voalte Admin Client.

### Hardware and devices
- RCB / RCB2 / RCB3: room-level device (room control board, unconfirmed) with audio, call switch and light
  connections. "Lost RCB" means the server lost contact with it. RCB Switch Disconnect: its call switch is unplugged
  or lost.
- GRS5 / GRS7 / GRS10 / GRS10H: room/unit station generations (GRS-10 = GRS10; "H" variant is GRS10H). They host
  audio stations and screens; they can get stuck in recovery mode, show screen faults, or reboot.
- SRS: station/room device, often replaced as a unit and reconfigured (unconfirmed expansion). ASBC / ASBC+: a
  separate device/product line named in cases (unconfirmed expansion).
- Duplo: device platform and firmware (emb-duplo-app); DTS = Duplo Test Stand; UCTS = Universal Collector Test
  Stand; DUT = device under test (RCB3, GRS7, GRS10H); OTS = off-the-shelf.
- Audio Station (AS): audio endpoint; Primary Audio / Secondary Audio are the main and backup stations. "Unconfigured
  AS" means a station that is present but not provisioned.
- Dome light: corridor light over a room door. Console / Primary Console: staff-facing call console.
- NUC: small compute node used in the unit/edge. POE: power-over-Ethernet switch feeding devices; rebooting or
  replacing it often clears "Lost NUC"/"Lost device" alerts. UPS: power backup. Tower: server tower.
- Serial number, "old vs new serial": evidence of a hardware swap (RMA).

### Software, services and integrations
- Enterprise server / Unit Server: central and per-unit servers. "Lost Unit Server" = unit server unreachable.
- ECT: engineering/configuration tool used for device configuration and viewing active calls (unconfirmed expansion).
- Smart Client: staff-facing client (badge number, staff assignment). Admin Client: configuration UI.
- Alert Manager: routes alerts to recipients. Alert / Call / Stuck alert: an alert that does not clear.
- System alerts: server-generated alerts named "Lost ..." (Lost RCB, Lost Primary Audio Station, Lost Unit Server,
  Lost NUC, Lost Mobile Device Provider, Lost Dome light, Lost Central ...).
- Mobile Device Provider / messaging service: delivers alerts to phones. Vocera and Voalte are staff communication
  endpoints. PBX / VoIP / SIP / FreeSWITCH: telephony and voice-path components; "busy signal" and no/one-way audio
  point here.
- ADT: Admit, Discharge, Transfer (HL7) feed of patient/room assignment; Mirth Connect: HL7 interface engine.
  Epic: EHR source. NPS: Nursecall Patient Safety (formerly NaviCare Patient Safety). PAL: patient-assignable
  location (room + bed designator). Bed Exit / bed connectivity: bed data integration. RTLS: real-time locating.
- SQL / database, VNC / SSH: remote-access and admin tools used by support. MAC: moves/adds/changes team.
- FST: field service technician (onsite). RMA: return merchandise authorization. NPD####: design document number.

### Support-case vocabulary
- Remote assessment, troubleshooting, test results, "No problems found" / "No issue found" / "Could not duplicate" =
  no fault confirmed; contrast with Device failure (hardware replaced) and Software/config issue (restart, reconfigure,
  upgrade).
- "Same issue occurred before": repeat failure (RA_Did_same_issue_occur__c).
- Locations (ED, ICU, PACU, OR, NICU, Med Surg, Cath Lab, floors, wings) describe where, not what: never cluster by
  location, customer, floor, serial number or person.

### Clustering rules
1. Cluster by failure mode / intent (what went wrong, which function was affected, and what fixed it), not by
   wording, site, device serial, or technician.
2. Prefer clusters that would map to one engineering or support action. A cluster is typically a symptom family
   (for example lost audio, lost device alerts, device reboot/stuck, screen/display fault, integration/message error,
   configuration/software, no fault found, informational/other).
3. Product (RCB, GRS10, SRS, ...) is a useful sub-cluster axis only when behavior differs by product; synonyms such
   as "GRS-10", "GRS10" and "Nurse Call - GRS10" are the same product.
4. Sub-clusters split a cluster by cause, component or resolution. Keep sub-cluster labels short.
5. Use only the supplied evidence; do not invent causes. Cases with missing information go to the closest cluster
   by reported issue, or to "Insufficient information".
