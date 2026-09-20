# Privacy e dati

*Read this document in English: [PRIVACY.md](PRIVACY.md).*

Kingmaker Kingdom Manager è un programma che fai girare tu. Dietro non c'è nessun servizio:
l'autore non gestisce server, non riceve dati, non tiene conto di chi lo usa e non raccoglie
statistiche né rapporti di errore. Tutto ciò che l'app sa vive sul computer di chi ospita la
partita, nelle cartelle `saves` e `assets` accanto al programma.

Questa pagina dice cos'è, cosa esce da quel computer in ciascun modo di giocare, e chi ne
risponde. Lo stesso testo, più breve, è nell'app sotto *Manuale → Privacy e licenze*, dove ogni
giocatore può leggerlo.

## Cosa conserva l'app

Solo sul computer di chi ospita:

- **Account** — nome utente, un'impronta PBKDF2-HMAC-SHA256 con sale della password (la password
  in sé non viene mai conservata), ruolo, lingua e unità dell'interfaccia, data di creazione e
  ultimo accesso. Nessun indirizzo e-mail, nessun nome vero, nient'altro viene chiesto.
- **La partita** — il regno, gli insediamenti, la mappa con la nebbia e le note del GM, i
  personaggi e i veicoli, i viaggi, il calendario.
- **Il diario** — il registro delle azioni nel regno, ogni riga con il nome utente di chi ha
  agito. Quando un amministratore guarda la partita come un altro account, il diario lo dice.
- **Immagini** — la mappa, i ritratti e i segnalini dei personaggi, caricati dal tavolo. Un
  ritratto può essere la foto di una persona vera: resta dove è stato caricato ed è servito
  solo a chi è entrato.
- **Il cookie di sessione** — un cookie firmato che ti tiene collegato. È l'unico cookie che
  l'app imposta, è strettamente necessario perché l'accesso funzioni, e non traccia nulla. Il
  suo contenuto (l'id del tuo account e la lingua) è conservato sull'host in `.nicegui/`.
- **Tentativi di accesso** — contati in memoria, per nome utente e per indirizzo, per rallentare
  chi prova le password. Non vengono mai scritti su disco e spariscono quando il server si
  ferma.

I file di salvataggio (lo zip della scheda Salvataggio, un `kingmaker.db` nudo) e le copie che la
sincronizzazione cloud carica contengono **tutto quanto sopra, impronte delle password
comprese**. Trattali come privati: tienili come copie di sicurezza, portali su un altro PC, ma
non pubblicarli da nessuna parte.

## Cosa esce dal computer di chi ospita

**Solo su questo computer, o sulla stessa rete** — niente. Pagine, script, fogli di stile e
caratteri arrivano tutti dall'host; il browser di un giocatore non parla con nessun altro.
L'app funziona anche con internet staccato.

**Online, tramite NiceGUI On Air** — il traffico del gioco passa da un relay gestito da
[Zauberzeug GmbH](https://zauberzeug.com/) (Germania), gli autori di NiceGUI, secondo le loro
[condizioni](https://nicegui.io/on_air). Il relay vede l'indirizzo di ogni giocatore e il
traffico lo attraversa in chiaro: il gestore potrebbe leggerlo. Va bene per una partita, non
per qualcosa che chiameresti un segreto. Il token On Air, se ne usi uno, è conservato in chiaro
nella cartella della partita.

**Con il cloud (ospitare da più PC)** — il launcher che ospita carica, in una cartella nel
Dropbox dell'amministratore: una copia dell'intero database (account e impronte delle password
comprese) ogni pochi minuti mentre qualcosa cambia, le immagini una volta sola, e un piccolo
record che nomina l'host — l'id casuale del suo launcher, il **nome utente di Windows o Linux e
il nome del computer** di chi ospita, l'indirizzo della partita e la versione dell'app. A quella
cartella si applica l'[informativa sulla privacy](https://www.dropbox.com/privacy) di Dropbox, e
l'app Dropbox che l'amministratore crea per essa è sua, secondo le condizioni per sviluppatori
di Dropbox. Ogni GM segnato *Può ospitare* riceve la credenziale Dropbox dell'amministratore per
quella cartella: è lo stesso accesso che ha l'amministratore, e non si può revocare a un host
senza revocarla a tutti (da *App collegate* di Dropbox, dopo di che tutti si ricollegano).

**Il launcher** — a ogni avvio chiede a GitHub se esiste una release più nuova, il che dice a
GitHub l'indirizzo del PC dell'host e la versione dell'app, nient'altro. *Impostazioni → Chiedi a
GitHub se c'è una versione nuova all'avvio* lo spegne; *Versioni su GitHub…* chiede comunque
quando lo premi. Scaricare un aggiornamento prende l'installatore da GitHub e, su Windows, lo
avvia: l'installatore non è firmato con un certificato a pagamento, ed è per questo che Windows
avverte la prima volta.

Nient'altro esce mai dalla macchina. I caratteri un tempo venivano caricati da Google Fonts dal
browser di ogni giocatore, che consegnava a Google l'indirizzo del giocatore a ogni pagina; ora
l'app li serve da sé.

## Chi ne risponde

Chi ospita la partita detiene i dati dei giocatori e ne risponde secondo la legge sulla privacy
che si applica a lui — nell'UE il GDPR, per il quale l'host è il *titolare del trattamento*. Per
un tavolo di amici vuol dire soprattutto: dire loro quanto sta scritto sopra, cancellare ciò
che chiedono di cancellare, e non condividere il salvataggio. L'autore del programma non è parte
di nulla di tutto questo e non tratta alcun dato.

**Cancellare.** Un amministratore cancella un account dalla finestra degli account (l'icona 👤⚙
nell'intestazione) e sostituisce o toglie un'immagine dalla scheda o dalla mappa dove è stata
caricata. Cancellare le cartelle `saves` e `assets` toglie tutto; la disinstallazione chiede se
farlo.

## Licenze e regole del gioco

Il programma è sotto [licenza MIT](LICENSE). Le regole del gioco sono Open Game Content secondo
la [Open Game License v1.0a](OPEN_GAME_LICENSE.md), e i nomi Pathfinder e Kingmaker compaiono
secondo la Community Use Policy di Paizo — vedi [NOTICE.md](NOTICE.md). Questo progetto non è
pubblicato, approvato né avallato da Paizo Inc., ed è gratuito.

L'app installata include software di altri — NiceGUI e i pacchetti Python su cui poggia, le
librerie Vue, Quasar e Tailwind che serve al browser, Python stesso con Tcl/Tk, il bootloader di
PyInstaller, le icone Material, e i tre caratteri dell'interfaccia (Cinzel, IBM Plex Sans e
Press Start 2P, sotto SIL Open Font License). Le loro licenze sono in `THIRD_PARTY_LICENSES.txt`
accanto al programma installato; dal sorgente, `python packaging/third_party.py` scrive lo
stesso file per il tuo ambiente.