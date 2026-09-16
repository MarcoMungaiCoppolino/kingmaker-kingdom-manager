# Kingmaker Kingdom Manager — guida utente

*In English: [../user-guide.md](../user-guide.md).*

Questa guida descrive l'app com'è alla versione 1.1.1, scheda per scheda, con il perché di ogni
scelta. Per installarla e avviarla vedi il [README.it.md](../../README.it.md); la finestra
dell'app installata è il primo capitolo qui sotto. Le schermate in
[`manual/img/screenshots/`](../manual/img/screenshots/) sono dell'interfaccia italiana.

I nomi di pulsanti e riquadri qui sotto sono quelli dell'interfaccia in italiano; in inglese
cambiano di conseguenza (*Viaggio* → *Travel*, *Acque* → *Waters*, *Regia* → *GM Screen*,
*Compagnia* → *Party*, *Trasporti* → *Transport*).

## Il launcher

![Il launcher](../manual/img/screenshots/launcher.jpg)

L'app installata (il setup per Windows o l'archivio per Linux dalla pagina delle release) apre
questa finestra al posto di un terminale; dal sorgente è `python launch.py --launcher`. Avvia
e ferma il server, nient'altro: si gioca sempre nel browser. La schermata è dell'interfaccia
inglese; in italiano i pulsanti sono *Avvia*, *Ferma*, *Apri nel browser*, *Copia*,
*Impostazioni*.

**Dove si gioca?** *Solo su questo computer* è la scelta predefinita: il gioco si apre nel tuo
browser e nessun altro lo raggiunge. *Sulla stessa rete* è per gli amici nella stessa casa:
aprono il link di rete nel loro browser. *Online, con amici lontani* pubblica il gioco tramite
il relay NiceGUI On Air; il tuo computer deve restare acceso, perché il regno vive lì. La scelta
viene ricordata.

**Il token On Air.** Scegliendo *Online* compare il campo e i tre passi: premi *Ottieni un
token*, registrati su nicegui.io (gratis), copia il token che la pagina mostra, incollalo qui.
Con il token il tuo indirizzo resta lo stesso a ogni avvio; senza, ogni volta un indirizzo
casuale nuovo. Il token è conservato in chiaro nella cartella della partita; il relay trasporta
il traffico del gioco e potrebbe leggerlo: va bene per una partita, non per dei segreti.

**Avvia, Ferma, i link.** *Avvia* fa partire il server; quando è pronto la riga di stato
diventa verde, il browser si apre e compaiono i link con un pulsante *Copia* ciascuno: questo
computer, la rete (una riga per ogni indirizzo della macchina; prova quello che somiglia alla
tua rete di casa), online. *Ferma* chiude il server in modo pulito, con l'ultimo salvataggio
scritto. Anche chiudere la finestra lo ferma, dopo una conferma. Se la porta è occupata il
launcher prende la successiva e lo dice. Su Windows, il primo avvio *Sulla stessa rete* è
preceduto da un avviso: Windows chiederà se consentire l'app attraverso il firewall, e devi
premere *Consenti accesso*.

**Il primo avvio.** La password dell'amministratore è mostrata in una finestra, con *Copia*;
non viene mostrata più. Al primo accesso l'app chiede di cambiarla. Se va persa,
*Impostazioni → Reimposta la password dell'amministratore* (a server fermo) ne genera una nuova
e la mostra una volta.

**Una partita da altrove.** *Carica un salvataggio…* (a server fermo) prende il `kingmaker.db`
di un altro PC, o lo zip scaricato dalla sua scheda Salvataggio: mostra il nome del regno, gli
account e le immagini, chiede una volta, copia tutto e conserva il salvataggio precedente accanto. Si entra
poi con gli account di quel file. Lo stesso riquadro è nella pagina di creazione del regno, per
chi usa il sorgente senza launcher.

**Impostazioni.** La porta, la lingua del launcher (l'app ha il suo interruttore), se aprire
il browser all'avvio, *Apri la cartella della partita* (dove stanno `saves` e `assets`, per le
copie di sicurezza), e la reimpostazione dell'amministratore. *Mostra il registro* in basso
apre quello che il server stampa: è lì che si guarda quando si ferma da solo.

**Aggiornamenti.** Quando su GitHub c'è una release più nuova, una riga in alto lo dice. Su
Windows *Scarica l'aggiornamento* scarica l'installatore e lo avvia, conservando la partita; su
Linux apre la pagina della release. *Impostazioni → Versioni su GitHub…* elenca tutte le
release, dalla più recente, con quella installata segnata, e installa quella che scegli; tornare
a una versione più vecchia è permesso, con un avviso, perché un salvataggio scritto da una
versione più nuova può essere rifiutato da una più vecchia. La partita sta in `saves` e `assets` dentro la cartella
installata: un aggiornamento sostituisce il programma e le lascia, e la disinstallazione (in
*App installate*) chiede se cancellare anche loro.

## Giocare da più PC (il cloud)

Senza, la partita vive su un PC e il suo proprietario deve essere online perché qualcuno
giochi. Con il cloud, l'ospitare può passare tra le persone fidate del tavolo — l'amministratore
e i GM che l'amministratore segna *Può ospitare* nella finestra degli account — tramite una
cartella nel Dropbox dell'amministratore. I giocatori non ospitano mai e non hanno mai il
salvataggio: aprono l'indirizzo del tavolo, che resta lo stesso chiunque ospiti, perché gli
host condividono un solo token On Air.

![La procedura guidata](../manual/img/screenshots/wizard.jpg)

**L'amministratore, una volta.** Nel riquadro *Cloud* del launcher premi *Configura
Dropbox…*: sette passi con un'immagine ciascuno. Un account Dropbox gratuito; *Create app* nella
App Console di Dropbox con *Scoped access* e *App folder* (l'app vede solo la sua cartella); i
cinque permessi; l'*App key* incollata nel launcher, con il nome del tavolo; la pagina di
autorizzazione (Continue, poi Allow); il codice mostrato, da incollare; fatto. Solo l'amministratore ha bisogno di
un account Dropbox.

**Gli altri host.** Mentre l'amministratore ospita, il DM apre *Collegati a un tavolo…* nel
suo launcher: l'indirizzo del tavolo, il suo nome utente e la password. L'host controlla che
l'account possa ospitare e consegna ciò che serve al launcher; la password è usata una volta
e non conservata. Da lì in poi anche quel launcher può ospitare.

**Giocare.** *Avvia* chiede prima al cloud chi ospita. Nessuno: il launcher prende la
partita, carica dal cloud la copia più recente se è più nuova della sua, porta le immagini
che gli mancano e parte. Qualcuno: il riquadro dice «ospitata da X dal…», con *Entra* per
aprire il gioco lì. Mentre ospiti, il cloud riceve una copia della partita ogni pochi minuti
quando qualcosa è cambiato, le immagini una volta sola, e un'ultima copia quando premi
*Ferma*. Nella cartella restano cinque copie recenti e una al giorno per trenta giorni; il
totale resta sotto i cento megabyte per anni.

**Il *Prendi il controllo* dell'amministratore.** Compare quando ospita qualcun altro: il suo
server si ferma entro un minuto (può perdere gli ultimi minuti di gioco) e la partita passa a
te.

**Da sapere.** Il PC di un host ha tutta la partita, segreti e hash delle password compresi:
per questo ospitare è una decisione di fiducia, non una casella per tutti. La credenziale del
cloud è conservata in chiaro nella cartella della partita di ogni host, come il token On Air;
*Dimentica il cloud* la toglie, e l'amministratore può anche revocarla su Dropbox, dopo di che
ogni host si ricollega. Se il cloud non risponde, il launcher propone di ospitare senza, e lo
dice.

## Salvataggio (amministratori)

La scheda con l'icona di download, dopo la Regia, esiste solo per gli amministratori. Tre
riquadri:

- **Scarica tutto (.zip)** — un solo file con tutta la partita: il database (regno, mappa,
  acque, personaggi, veicoli, viaggi, account, diario), il regno in JSON leggibile, e ogni
  immagine di `assets` (la mappa, i ritratti, i segnalini). Tienilo come copia di sicurezza, o
  portalo su un altro PC. Una copia resta in `saves/backups/`.
- **Carica un salvataggio** — lo zip scaricato qui, o un semplice `kingmaker.db`. Una finestra
  dice cosa contiene il file (regno, account, immagini) e chiede; il salvataggio attuale viene
  copiato accanto a sé (`kingmaker.db.before-restore-<data>.bak`), poi il database è sostituito
  e le immagini scompattate in `assets`. Un file di una versione vecchia viene migrato entrando;
  uno di una versione più nuova è rifiutato. Se gli account del file non sono quelli attuali,
  tutti rientrano.
- **Ricomincia da capo** — svuota la partita e torna alla creazione del regno; gli account
  restano.

Lo stesso controllo *Carica un salvataggio* è nella pagina di creazione del regno, e il launcher
ha *Carica un salvataggio…* per lo stesso zip.

## Account e ruoli

Al primo avvio l'app crea l'account `admin` e stampa in console una password casuale: compare
una volta sola, appuntala. Al primo accesso ti chiede di cambiarla, e da lì crei gli account
degli altri: in alto a destra, accanto al tuo nome, l'icona 👤⚙ *Account dei giocatori* (la
vedi solo tu che sei amministratore). Ogni account nuovo nasce con una password generata da
mostrare al diretto interessato: non è recuperabile, ma puoi sempre generarne un'altra.

| Ruolo | Cosa può fare |
|---|---|
| **Amministratore** | Tutto, più gli account, il salvataggio e l'azzeramento del regno. |
| **Game Master** | Prepara la mappa e la sua immagine, conosce i segreti, decide cosa è stato rivelato e governa tutti i personaggi. |
| **Giocatore** | Gioca: attività, turno, città, mappa. |
| **Spettatore** | Guarda soltanto. |

### Personaggi

Un **Ruolo di Governo** non è più un nome scritto a mano: se la casella *PG* è spuntata, scegli
chi lo ricopre da un elenco di personaggi della campagna. I ruoli senza *PG* restano PNG con il
nome libero (Kesten, Oleg…), come prima.

Le schede stanno nella scheda **Compagnia**. Chi le vede dipende da chi sei:

* il **Game Master** e l'**amministratore** vedono tutti i personaggi, li creano, li eliminano e
  li collegano agli account;
* un **giocatore** vede e modifica soltanto i personaggi collegati al proprio account. Non è un
  pulsante nascosto: la scheda di un altro giocatore non viene proprio letta dal database.

Su ogni scheda ci sono, come su Roll20, un **ritratto** e un **segnalino**: il ritratto è
l'immagine grande della scheda, il segnalino è il tondino che compare sulla mappa, sull'esagono
dove si trova il personaggio. Si caricano dalla scheda stessa (PNG, JPG, GIF o WebP fino a 8 MB)
e finiscono in `assets/characters`, che come tutto il resto sta dietro l'accesso. Senza immagine
il segnalino mostra le iniziali nel colore del personaggio.

**Quello che finisce nella pagina è una copia rimpicciolita**, tenuta accanto all'originale, che
non si tocca. Il motivo è misurato, non teorico: un segnalino si disegna dentro un cerchio grande
come mezzo esagono, ma il file che il browser scaricava era quello caricato — due megabyte e
passa. Sul portatile di chi l'aveva caricato non si notava, perché stava già in cache; su un
altro dispositivo, dietro il relè di On Air, la mappa si ridisegna diverse volte mentre si apre e
ogni ridisegno rifà l'elemento dell'immagine: una decina di richieste dello stesso file grosso
tutte insieme, e un segnalino che non compariva mai. Adesso quel token pesa **60 KB invece di
2,2 MB**, e il ritratto della scheda 47 KB invece di 71.

La copia si fa una volta sola e serve senza rifarla; un JPEG resta un JPEG (rifarlo in PNG lo
faceva *crescere*), e se malgrado tutto non viene più leggera dell'originale si butta e si serve
l'originale — la ragione di esistere di una miniatura è pesare meno. Senza Pillow installata non
si fa niente e le immagini restano quelle di prima.

**Pubblicando con On Air, gli indirizzi scritti a mano portano il prefisso.** On Air non pubblica
l'app alla radice del dominio ma sotto un pezzo di percorso — `https://…/<nome>/device-0/` — e lo
dice all'app nell'intestazione `X-Forwarded-Prefix`. NiceGUI lo aggiunge da sé agli indirizzi dei
*suoi* elementi (`ui.image`, `ui.interactive_image`: lo fa nel browser con `window.path_prefix`),
ed è per questo che lo sfondo della mappa si è sempre visto. Ma il segnalino di un personaggio
sta dentro l'SVG che scriviamo noi, e lì non passa nessuno: un `/assets/…` scritto da noi puntava
fuori dall'app, e il segnalino non arrivava — **solo da fuori casa**, perché in locale il
prefisso è vuoto e non c'era niente da sbagliare.

Adesso il prefisso lo legge la pagina quando si apre e se lo tiene la finestra, e ce lo mettiamo
noi sugli indirizzi che finiscono in markup nostro. Su quelli che passano da un elemento di
NiceGUI **non** va messo: glielo mette già lui, e metterlo due volte è peggio che non metterlo.

Il **rimando alla pagina di accesso** è di quest'ultima specie, e ci abbiamo sbattuto contro.
NiceGUI ha un `RedirectWithPrefixMiddleware` che aggiunge il prefisso a ogni `Location` che
comincia per «/»: il nostro rimando ce lo metteva a sua volta, e usciva scritto due volte —
`/<nome>/device-0/<nome>/device-0/login`, un indirizzo che non esiste. Il browser lo seguiva, si
ritrovava rimandato, e dopo qualche giro si arrendeva con «ti ha reindirizzato troppe volte».

Il guasto è rimasto nascosto per la ragione peggiore: **chi era già entrato non lo vedeva**. Con
la sessione in tasca quel rimando non scatta mai. Lo trovava solo chi arrivava per la prima volta
— cioè esattamente la persona che non aveva modo di aggirarlo. Adesso mandiamo un `/login` nudo e
il prefisso lo mette NiceGUI, una volta sola.

**E se l'immagine non arriva lo stesso, si vedono le iniziali.** Sulla mappa il tondino con le
iniziali nel colore del personaggio si disegna *sempre*, e l'immagine ci va sopra: se non
arriva, sotto c'è comunque un segnalino leggibile invece di un buco. Nella fila dei ritratti
l'immagine è uno **sfondo** e non un `<img>`, per la stessa ragione: un `<img>` che fallisce
disegna l'icona di immagine rotta, uno sfondo che fallisce non disegna niente e lascia vedere le
iniziali che stanno dietro. Nessun javascript, solo il caso normale del CSS.

Sempre dalla scheda si impostano:

* **Velocità di base** — quella scritta sulla scheda del personaggio;
* **Bonus** — i metri in più da talenti, oggetti o incantesimi, tenuti separati per vedere da
  dove arriva il totale;
* **Modificatore di Costituzione** — quanti giorni di marcia forzata regge;
* **colore**, **posizione sulla mappa**, **veicolo** su cui è salito — solo fra quelli posati nel
  suo stesso esagono — e note.

Sotto ai numeri l'app mostra subito quante attività di esplorazione al giorno vengono fuori da
quella Velocità, secondo la tabella dell'Esplorazione degli Esagoni.

Il vantaggio pratico dei personaggi è che due ruoli dello stesso personaggio ora sono davvero la
stessa persona: le **Attività di Governo** disponibili in un turno si contano sui PG distinti,
non sui nomi uguali. Passando da una partita precedente i nomi già scritti diventano personaggi
da soli, senza doppioni.

### Trasporti

La scheda **Trasporti** è l'elenco dei veicoli che il regno possiede. Ha una pagina sua e non un
riquadro in fondo alla Compagnia perché risponde a un'altra domanda e a un'altra regola: un
personaggio lo modifica chi lo interpreta, un veicolo è del regno e lo gestisce chiunque ci
giochi. Si
sceglie da un catalogo di 45 veicoli trascritti da
[pf2.altervista.org/wiki/Veicoli](https://pf2.altervista.org/wiki/Veicoli): nome, livello,
prezzo, taglia, equipaggio, passeggeri e Velocità, esattamente come stanno sulla pagina.

Dentro, i mezzi stanno divisi per **dove vanno**: la **Stalla** quelli di terra, il **Porto**
quelli d'acqua, e il **Cielo** quelli che volano — quest'ultimo compare solo se ne avete uno.
Non è un ordinamento estetico: è l'unica differenza che il viaggio guarda davvero. Una barca
attraversa un Confine d'Acqua e può seguire il corso di un fiume; un carro si ferma sulla riva
come chi va a piedi; chi vola passa sopra tutti e due, perché la wiki li mette insieme — «Se voli
o viaggi sull'acqua, quasi tutti gli esagoni sono terreno aperto» — ma un fiume non è una strada
per lui: ci passa sopra, non lungo.

**Dove va un mezzo lo dice la wiki, non il tavolo.** Si guarda il movimento più veloce fra quelli
scritti sulla sua pagina: l'Apparato del Polipo cammina a 1,5 m e nuota a 12, ed è una cosa
d'acqua. Una Barca a Remi nasce in Porto senza che tu debba dirglielo. Quando la pagina non dà
nessuna Velocità — un carro va quanto la creatura che lo traina — l'app non indovina: lo mette in
Stalla e la tendina *Dove va* ti dice perché. Quella tendina resta comunque tua: se avete
costruito una zattera che il catalogo non conosce, la sposti a mano e la tua scelta vince.

Di ogni esemplare puoi dire il nome che gli avete dato, se è **disponibile** (toglilo quando è
rotto, prestato o lontano) e due note. Assegnandolo a un personaggio, il viaggio conta la
Velocità del veicolo invece che quella a piedi; più personaggi sullo stesso veicolo viaggiano
insieme, e se sono più dei posti scritti sulla pagina l'app te lo fa notare senza impedirtelo.

Per parecchi veicoli la wiki **non dà una Velocità in metri**: un carro va quanto la creatura
più lenta che lo traina, un velocipede quanto il suo pilota. In quei casi l'app non inventa un
numero: te lo chiede, dicendoti perché. Finché non lo scrivi, chi ci sta sopra viaggia a piedi.

Chi ci sta sopra **non si decide da qui**. C'era una tendina *A bordo*, comoda, e diceva una cosa
falsa: che si può salire su una carrozza da qualunque parte del regno. Salire è un gesto che si fa
stando lì, e il posto dove si sta è la mappa — quindi è lì che si sale e si scende, e questa pagina
resta la **rimessa**: si comprano, si nominano, si contano i posti e la Velocità. Ogni riga dice
dove sta il mezzo e chi ci viaggia; il resto è nel *Viaggio*.

Ogni veicolo può avere una **immagine** e un **segnalino**, come i personaggi: stessi formati,
stesso tetto di 8 MB, e finiscono in `assets/vehicles`. Il segnalino compare sulla mappa
nell'esagono in cui il mezzo è stato posato — un cerchietto tratteggiato appena sopra la fila dei
personaggi — perché un veicolo sta in un posto, come chiunque altro. Un veicolo, un segnalino: la
carrozza è una sola anche se ci viaggiano in tre, e due mezzi fermi nella stessa cella si mettono
in fila invece di sovrapporsi. Senza immagine caricata compare il simbolo del mestiere — 🐎, ⛵ o
🎈 — e un veicolo segnato «non disponibile» si vede sbiadito.

Accanto alla Velocità c'è il numero di **posti**. Di norma arriva dalla pagina — i passeggeri più
il pilota, o il solo equipaggio quando i passeggeri sono «-» — e lo puoi correggere per il tuo
esemplare. Serve al viaggio: è il numero che dice se il gruppo ci sta tutto sopra.

**Salire tutti a bordo.** Nel riquadro *Viaggio*, se chi parte si porta dietro un veicolo compare
l'interruttore «Salgono tutti a bordo», **spento**. Acceso, il gruppo unito procede alla Velocità
del veicolo invece che a quella del suo membro più lento — ma solo se i posti bastano per tutti,
e solo se il veicolo è davvero più svelto di com'è il gruppo adesso: un carro pesante non
obbliga la compagnia a rallentare. Se i posti non bastano l'app te lo dice e resta alla regola
normale; chi ci sta comunque lo decidete voi facendoli salire.

Cambia più di quanto sembri. Finché il gruppo va come il più lento, ritrovarsi non fa mai
guadagnare un giorno a nessuno: il raduno serve a stare insieme, non ad arrivare prima. Appena il
gruppo unito è più veloce, incontrarsi diventa un guadagno vero, e **il ritrovo si sposta da solo
verso chi è rimasto indietro**: è il carro che va a prendere il lento. Non c'è nessuna regola in
più scritta per ottenerlo — è lo stesso conto del raduno, con un numero diverso.

È spento di proposito. L'Esplorazione degli Esagoni non parla di veicoli, e far viaggiare una
compagnia in carrozza è una decisione del tavolo: non la prende l'app.

Accenderlo o spegnerlo su un viaggio già disegnato **non ne sceglie un altro**: la strada resta
quella che hai tracciato e cambiano solo i giorni, che è la domanda che ti stavi facendo. Vale
anche per la marcia forzata.

Le password non sono salvate: se ne conserva solo l'impronta PBKDF2-HMAC-SHA256, con un sale
diverso per ognuna, nella tabella `users` di `saves/kingmaker.db` — sul tuo disco, come tutto il
resto. Nessun servizio esterno le vede: NiceGUI è solo la libreria che disegna le pagine, non
tiene account. La chiave che firma i cookie di sessione sta in `saves/.storage_secret`, generata
al primo avvio; puoi imporne una tua con `KINGMAKER_STORAGE_SECRET`. Cancellare quel file non
rompe niente: rimanda solo tutti alla schermata di accesso. Attenzione però: chi copia la cartella
`saves/` copia anche quella chiave. Va bene sul PC di casa; su un servizio di hosting passala con
la variabile d'ambiente e non con la cartella.

Una password persa non si recupera, perché l'impronta non si può girare al contrario: se ne
genera un'altra dal pannello Account (🔑) e si consegna a chi la deve usare.

**Entrare in un altro account.** Dal pannello Account l'amministratore può guardare l'app con gli
occhi di un altro — l'icona 🔓 accanto a ogni riga — senza saperne la password e senza
cambiargliela. Serve a vedere davvero quello che vede un giocatore invece di indovinarlo, e a
non lasciare nessuno fuori dal proprio account per fare una prova. Non è un potere in più: chi
amministra ha già il file del database, e da lì una password la può riscrivere comunque. È solo
il modo onesto di farlo, e si vede che sta succedendo:

* l'intestazione dice **«nei panni di X»** in rosso, con accanto il pulsante per tornare indietro;
* il registro del regno segna chi è entrato in quale account, e resta scritto;
* il permesso si controlla su chi ha fatto l'accesso *davvero*, quindi indossare i panni di un
  giocatore non è una scala per risalire da qualche altra parte;
* niente cambio password forzato mentre sei negli altrui: quella la sceglie chi l'account ce l'ha.

**Cosa è condiviso e cosa no.** Il regno è uno solo: esagoni, scheda, turno, città e
calibrazione della griglia si aggiornano da soli in tutte le finestre collegate. Restano
personali l'esagono selezionato, lo zoom della mappa e le scelte nei menu a tendina, così due
giocatori possono lavorare su esagoni diversi nello stesso momento.

La partita vive in un database SQLite, `saves/kingmaker.db`, scritto al massimo una volta ogni
due secondi (e alla chiusura). Non viene riscritto tutto ogni volta: cambiano solo le righe che
hai davvero toccato.

Continua a valere una regola: fai girare **una sola** copia dell'app sugli stessi dati. Il
database regge bene più scritture, ma ogni processo tiene il regno in memoria e al salvataggio
sovrascriverebbe le modifiche dell'altro.

Se arrivi da una versione precedente non devi fare niente: al primo avvio il vecchio
`saves/regno.json` viene importato da solo nel database, e il file resta dov'è come copia di
sicurezza. Dalla scheda Salvataggio scarichi tutta la partita in un solo zip, con dentro il
regno in JSON.

Puoi spostare i dati altrove con la variabile d'ambiente `KINGMAKER_DATA_DIR` (e le immagini con
`KINGMAKER_ASSETS_DIR`): serve per il giorno in cui l'app girerà su un servizio di hosting invece
che su questo PC. Senza variabili resta tutto dov'è sempre stato.

## Il tempo che passa

In alto, accanto ai numeri del regno, c'è la data della campagna nel **Calendario di Absalom**
e quanto manca al prossimo Turno di Regno. Il Game Master ha i comandi: ▶ per far scorrere il
tempo, ⏸ per fermarlo, quattro velocità (un giorno di gioco ogni 12, 6, 3 o 1 secondo veri) e
📅 per sistemare la data a mano.

Il tempo scorre **sul server**, non nei browser: c'è un solo orologio per tutti, così due
finestre non contano giorni diversi. I giocatori lo vedono e basta.

Mentre i giorni passano, i gruppi in cammino avanzano da soli: ogni giorno spendono le loro
attività di esplorazione, e quando bastano a pagare la tappa entrano nell'esagono successivo.
Un esagono di palude con una sola attività al giorno prende tre giorni, e per due di quei tre
il gruppo è onestamente ancora nell'esagono di prima. Ogni passo finisce nel registro.

**Alla fine del mese il Turno di Regno avanza da solo e l'orologio si ferma**, così il tavolo ha
il tempo di giocarsi le Attività di Regno. Il turno riparte quando il GM rimette in moto il
tempo. La wiki dice che i turni di Regno «si verificano alla fine di ogni mese di gioco»
([Dirigere un Regno](https://pf2.altervista.org/wiki/Dirigere_un_Regno)), e i mesi di Golarion
vanno da 28 a 31 giorni: la durata di un turno è quella del mese in corso, non un numero tondo
deciso da noi. Calistril prende un giorno in più negli anni bisestili, uno ogni otto.

Se il server si riavvia con l'orologio acceso lo ritrovi fermo: far passare giorni mentre non
c'era nessuno a guardare non è quello che voleva chi l'aveva avviato.

## Le sezioni

### Creazione del Regno
Procedura guidata sulle dieci fasi del manuale: Concetto, Concessione, Territorio Centrale,
Governo, Finalizzare i Punteggi, Dettagli, Ruoli di Governo (con i quattro ruoli investiti e
le abilità che addestrano), Primo Villaggio, Modificatori di Abilità, Fama o Infamia.
I punteggi si aggiornano in tempo reale mentre scegli.

Sotto le dieci fasi, chi può azzerare il regno vede **Hai già un salvataggio?**: lo stesso
controllo *Carica un salvataggio* della scheda Salvataggio, per una partita giocata su un
altro PC o prima dell'installatore. Niente da rifare: il file viene guardato, confermato e
copiato dentro.

### Mappa
Griglia esagonale sovrapposta all'immagine della mappa. Per ogni esagono puoi registrare
stato (Sconosciuto / Ricognito / Liberato / Rivendicato), terreni, Elementi del Terreno
(Risorsa, Punto di Riferimento, Rifugio, Rovine, Ponte, Struttura…), strade, fortificazioni,
Terreni Agricoli e Siti di Lavoro. Dal pannello laterale tiri direttamente le Attività di
Regione sull'esagono selezionato: Rivendicare, Liberare, Stabilire un Sito di Lavoro,
Stabilire Terreno Agricolo, Costruire Strade, Fortificare, Stabilire un Insediamento.
Costi in PR, PE e Ricompense Miliari sono applicati automaticamente.

**Icone:** il pulsante *Icone* in cima alla mappa nasconde icone e nomi degli esagoni e lascia
solo il disegno. Servono a dire cosa c'è su un esagono, e per quello sono giuste; ma quando stai
seguendo un fiume o tirando una rotta ti stanno davanti proprio dove guardi. **I segnalini dei
personaggi restano**: quelli sono il *dove sei*, non il *cosa c'è*, e senza non si capirebbe più
niente della mappa.

**Immagine di sfondo:** apri *Calibrazione della griglia* e carica la mappa delle Terre Rubate
(PNG/JPG), oppure copia il file dentro `assets/` e sceglilo dal menu a tendina.
Le dimensioni dell'immagine vengono rilevate da sole; premi *Adatta la griglia all'immagine*
per distribuire le colonne sulla larghezza, poi ritocca orientamento, raggio e origine X/Y
finché i poligoni coincidono con gli esagoni stampati. Lo zoom sotto la mappa ingrandisce
fino al 400% con scorrimento, utile sulle mappe molto grandi. Per spostarsi si tiene premuto il
tasto destro (o la rotella) e si trascina, come su Roll20: con le sole barre di scorrimento, senza
touchpad, è una sofferenza.

**Campiture del terreno.** Sotto lo zoom c'è un secondo cursore, *Campiture*: quanto i colori del
terreno coprono l'immagine della mappa. La mappa delle Terre Rubate ha già i suoi colori, e una
campitura che dice «qui è foresta» sopra una foresta disegnata copre il disegno invece di
aggiungerci qualcosa — a volte si vuole guardare la mappa, a volte la sua classificazione. I due
pulsanti ai lati sono le due posizioni che si usano davvero: solo il disegno, o campiture piene.

**I bordi degli esagoni non sbiadiscono insieme ai colori.** È la scelta che rende il cursore
usabile fino in fondo: a campiture spente si vede ancora dove finisce un esagono e dove comincia
il vicino, quindi si può giocare così e non solo sbirciare. Tecnicamente la trasparenza si
moltiplica nel **canale alfa** del colore invece di aggiungere un `fill-opacity` al gruppo: un
attributo sul gruppo si porterebbe dietro anche i contorni.

Il velo è **personale**, come lo zoom: la scheda del regno lo ricorda per la volta dopo, ma quello
che la tua finestra ha in mano vince. Il GM può tenere le campiture piene per lavorare mentre i
giocatori si guardano il disegno.

**La mappa si ricorda dove stavi guardando.** Cambiando scheda e tornando sulla Mappa ci si
ritrovava all'angolo in alto a sinistra: chi gioca nella metà destra delle Terre Rubate doveva
rifare la strada ogni volta. La posizione si tiene come **frazione** di quanto c'è da scorrere e
non in pixel, così cambiando ingrandimento si resta sullo stesso pezzo di mappa invece che sullo
stesso numero di punti.

La parte scomoda è che lo scatto che riporta a zero non arriva come un evento di scorrimento: non
c'è niente da intercettare. Ci si aggancia allora alla sola cosa che lo precede sempre — un clic
**fuori** dalla mappa, che è come si cambia scheda — e si sorveglia per un secondo, perché
rimettere a posto *prima* che lo scatto arrivi non serve a niente. La regola che tiene in piedi il
resto è che **la mano ha sempre ragione**: ogni gesto sulla mappa (rotella, trascinamento, tasti)
segna l'ora, e si corregge solo quello che nessuna mano ha chiesto. Il conto va a tempo e non a
fotogrammi: quando la finestra non sta disegnando — un'altra finestra davanti, la scheda in
secondo piano — i fotogrammi non girano, ed è proprio quel caso in cui la mappa deve essere già a
posto quando torni a guardarla.

**Segnalini dei personaggi.** Chi è sulla mappa compare come tondino in basso nel suo esagono,
con il ritratto caricato dalla scheda o le iniziali nel suo colore. Valgono le stesse regole
della nebbia: un giocatore non riceve i segnalini che stanno su esagoni che non conosce — ma
vede sempre i propri personaggi, perché dove si trovano lo sa comunque.

**Muovere i personaggi.** Sotto la mappa c'è la fila dei ritratti: chi è in campagna, dove si
trova e, se è in cammino, una barretta con i giorni che mancano. Un personaggio che non è ancora
sulla mappa dice «fuori mappa»: cliccalo e poi clicca l'esagono dove si trova, ed è posizionato.

Per farlo viaggiare ci sono due strade, e fanno la stessa cosa:

* **dalla mappa**, come in un gioco di strategia. Accendi il pulsante **Viaggio** sopra la
  mappa: la colonna di destra passa al riquadro *Viaggio* e mette via la Regia e la scheda
  dell'esagono, che tornano appena la spegni. Finché è acceso il clic sulla mappa non sceglie
  più esagoni — sceglie chi parte:
  * **clic su un esagono** → prende tutti i segnalini che ci stanno sopra, che di solito è il
    gruppo che viaggia insieme;
  * **clic su un segnalino** → prende solo quello;
  * **clic sul tondo di un mezzo** → prende quel mezzo, e da lì si viaggia con lui;
  * **ctrl + clic** → somma alla scelta invece di ricominciare, così si mette insieme un gruppo
    prendendo i personaggi uno per uno anche da esagoni diversi. Finché tieni premuto ctrl la
    freccia non parte: stai scegliendo, non tracciando;
  * **clic dove non c'è nessuno** → lascia perdere tutto.

  Attorno ai segnalini scelti compare lo stesso tratteggio bianco dell'esagono selezionato, così
  vedi chi hai in mano.

  **Un segnalino per pezzo di esagono, grande quanto il pezzo lo concede.** Dove l'acqua divide un
  esagono ogni pezzo ha il suo tondo, e il tondo si misura sul pezzo: in un esagono intero è grande
  come è sempre stato, in mezzo esagono un po' meno, e dentro un pezzo piccolo come un
  ventiquattresimo di esagono diventa piccolo ma resta dentro il suo pezzo — non sborda e non copre
  i vicini. Così anche un pezzo minuscolo è un posto in cui si può stare, si può indicare col
  righello e si può cliccare: il bersaglio del clic resta largo anche quando il disegno è piccolo.

  **Dove sono in più di uno, il tondo porta il numero** invece della faccia di uno dei tanti: una
  faccia chiede spazio per essere riconosciuta, un numero si legge anche piccolo. Cliccandolo si
  apre il riquadro con i ritratti e i nomi — lì grandi — e si sceglie chi muovere, o «Tutti e N».
  Con **ctrl+clic** se ne sommano più d'uno alla volta, persone e mezzi (anche due barche ferme
  sullo stesso incrocio: una alla volta, con chi c'è sopra), poi «Prendi i scelti».
  Con ctrl invece si somma tutto il gruppo senza aprire niente.

  **Si viaggia anche dentro l'esagono in cui si sta**: da una sponda all'altra senza uscirne, e
  costa la strada — i pezzi che attraversi — e nessun esagono, perché in nessun esagono entri. E
  **premere dà subito la via più corta** fino a dove hai premuto, anche se è la cella accanto: la
  guida a mano comincia dal secondo passo. Da dentro un pezzo piccolo di esagono era il modo per
  non restare incollati al segnalino.

  **Un mezzo posato è un'unità: lui e chi c'è sopra.** Chi è a bordo non ha un tondo suo — sta
  dentro quello del mezzo, in piccolo — e il mezzo sta nel tondo del suo pezzo come una persona: da
  solo ha il suo tondo, con le facce dentro; nello stesso pezzo di qualcuno che va a piedi fanno un
  gruppo col numero, dove il carro con due sopra e uno a terra fanno **due**, non tre. Dal riquadro
  si vede il mezzo con le facce di chi ci sta sopra e, a parte, chi va a piedi: si prende il mezzo
  (e vengono tutti quelli sopra) o una persona a terra. E **si sale solo dallo stesso pezzo di
  esagono** — un fiume in mezzo non si scavalca per salire su un carro. Alla partenza il mezzo si
  lascia come si lasciano le persone: restava in mano, illuminato, a viaggio già partito.

  **Viaggiando insieme, il ritrovo è una sponda**, non un esagono: i rami di avvicinamento ci
  arrivano tutti, la strada comune ne parte, e sulla mappa si attaccano nello stesso punto.

  **Gli altri vedono la stessa freccia che vedi tu**, punto per punto — mentre la trascini e
  quando il piano è fatto — anche per un viaggio dentro un esagono solo.

  **Si arriva nel pezzo che hai puntato.** Il righello lascia indicare una sponda qualunque
  dell'esagono d'arrivo, e il viaggio ci si ferma: porta con sé il punto, non solo le due
  coordinate. Fermarsi di là dall'acqua costa il pezzo di strada che ci vuole per arrivarci — su una
  confluenza a tre sponde con due ponti, fermarsi dove si entra costa 2 attività, nella sponda
  accanto 2½, in quella di là 3½. Se in quel pezzo, entrando da lì, non ci si arriva, l'app lo dice
  e il viaggio si ferma sulla sponda d'ingresso.

  **Attraversare due volte dentro lo stesso esagono si può**, e serve: con due ponti in catena si
  arriva anche nel pezzo che non confina col lato da cui sei entrato. Ogni passo dentro un esagono
  costa **un quarto** di quell'esagono, quindi quattro passi fanno un'attività, come attraversarlo:
  girare in tondo si può, ma si paga, e il conto lo vedi salire mentre trascini.

  **Quello che vedi mentre trascini è quello che paghi, e quello che resta.** Il righello e il server
  fanno lo stesso conto, per **atomi**: l'esagono è diviso in 24 pezzi fissi, l'acqua chiude i
  passaggi fra loro, e ogni pezzo in cui entri costa un quarto dell'esagono. Dentro un esagono la
  strada tocca le sponde che hai toccato tu, nell'ordine in cui le hai toccate — e la freccia passa
  per gli stessi pezzi, mentre trascini e dopo che hai lasciato. Quattro pezzi sono un esagono tagliato
  dritto, cioè quello che dice la wiki; un giro in più costa quanto è lungo, e girare in tondo si vede
  costare. Al browser non arriva il grafo: arriva la regola — la geometria dei 24 pezzi una volta, e
  per ogni esagono con acqua un numero di 36 bit che dice quali passaggi sono chiusi.

  **Chi è a bordo si disegna dentro il tondo del mezzo**, in piccolo lungo il bordo di sotto — la
  stessa lingua del «×2» di un Esagono Risorsa e del lucchetto di ciò che i giocatori non vedono
  ancora. Prima gli stava accanto, e con tre passeggeri l'esagono diventava una fila di facce in cui
  il mezzo era solo un'altra pastiglia: non si vedeva più chi viaggia **con** chi. Oltre i tre
  compare un «+n», come già fa la fila quando l'esagono è affollato. E siccome un segnalino lo si
  prende dove è disegnato, chi è a bordo non si clicca da solo: si clicca il mezzo, e vengono con
  lui.

  **Chi si sceglie porta con sé il mezzo su cui viaggia, e solo quello.** Prendendo qualcuno che sta
  su un carro si accende anche il carro — è la stessa cosa che parte, e sulla mappa si illuminano
  tutti e due con lo stesso anello. Prendendo invece qualcuno che va a piedi, il mezzo che avevi in
  mano si lascia: con una barca ancora presa, cliccare una persona a riva non cambiava niente,
  perché il viaggio restava quello d'acqua.

  Fra i tre l'ordine conta, ed è questo: **una faccia prima di un mezzo, un mezzo prima della
  terra**. Prima bastava cliccare l'esagono per prendere il mezzo che ci stava, e andava finché i
  mezzi erano solo barche in mezzo all'acqua, dove segnalini di gente non ce ne sono. Appena i
  carri sono arrivati sulla mappa quella regola si è mangiata il gesto più importante che c'è — un
  carro sta *insieme* ai suoi passeggeri, e il clic finiva sempre su di lui: il riquadro del
  gruppo sembrava sparito. I tondi non si sovrappongono mai (le facce stanno sotto il centro, i
  mezzi sopra), quindi ognuno si prende dove è disegnato.
  Poi, per dirgli dove andare:
  * **trascina col tasto sinistro**, come il righello di Roll20. Un clic secco non disegna
    niente: quello è il gesto per scegliere chi parte, e vedere la freccia lampeggiare a ogni
    scelta era solo fastidio. Diventa un tratto o appena muovi la mano, o se **resti premuto
    fermo** un quarto di secondo: da lì la freccia compare e va da sola fin lì per la via più
    economica. **Se la freccia si vede, rilasciare la conferma** — quello che vedi e quello che
    succede sono la stessa cosa, ed è l'unico modo perché il gesto si impari da solo. Ma se
    continui a trascinare di
    esagono in esagono **il cammino segue la mano**, anche quando è più lungo: se vuoi passare
    per la foresta invece che per la strada, o toccare un esagono per strada, basta portarci
    sopra il mouse. Tornando indietro sui tuoi passi il cammino si accorcia, così si corregge
    senza mollare il tasto; saltando lontano si riempie **tirando dritto**, e solo dritto.
    L'etichetta aggiorna attività e giorni sul percorso che hai davvero disegnato, non su
    quello che l'algoritmo avrebbe scelto. Quando lasci il tasto il percorso è deciso.

    **Il cammino può incrociare se stesso**, e ripassare da un esagono dove è già passato. Prima
    non poteva, e insieme a sé vietava una strada che sulla mappa esiste: entri in un esagono
    tagliato da un fiume, prosegui, giri, e più avanti un ponte ti riporta sull'altra sponda dello
    **stesso** esagono. Quella sponda non si poteva più raggiungere, perché l'esagono «era già
    stato usato». Ogni passaggio si paga: il conto somma i passi e non gli esagoni, quindi passare
    due volte costa due volte — contarli una sola sarebbe la scorciatoia che fa arrivare prima chi
    gira di più.

    Restava da distinguere le due intenzioni, che con la sola mappa si somigliano: *sto tornando
    indietro* e *sto chiudendo un giro*. Le separa una cosa sola, ed è esatta — tornare indietro
    vuol dire rientrare nella cella **da cui si è appena usciti**; arrivarci da un'altra parte è
    un giro che si chiude. Cercare più indietro di così — a cinque passi, a dieci — non saprebbe
    più distinguerle, e si mangerebbe i giri.

    **La freccia entra in una cella nuova solo se la mano ci resta**, un decimo di secondo scarso.
    Senza, la cella si sceglieva col centro più vicino a ogni movimento del mouse, e il confine fra
    due celle è il lato dell'esagono: un pixel di tremolio lo attraversava. Sul lato non si vedeva —
    rientrare nella cella da cui esci accorcia, e il cammino resta lungo uguale — ma su un
    **vertice** si toccano tre celle, e girarci intorno di pochi pixel allungava il cammino di tre
    passi a giro. Da quando ripassare è permesso quei passi non si tolgono più da soli, e la
    freccia partiva in spirale.

    Chi entra **ben dentro** la cella non aspetta niente: il tremolio vive sui bordi, e chi passa
    vicino al centro ha già detto dove vuole andare. Senza questa scorciatoia una passata veloce non
    commetterebbe nessuna cella, e la strada verrebbe poi riempita dal cammino più economico invece
    che da quello che il dito ha seguito — esattamente ciò che la guida a mano esiste per evitare.
    Le due sponde di un esagono tagliato fanno eccezione: hanno lo **stesso** centro, «dentro» lì
    non vuol dire niente, e si aspetta sempre. E la cella che stava aspettando quando lasci il tasto
    si prende lo stesso: hai rilasciato lì dentro, ed è lì che volevi finire.

    **La linea sfuma sugli ultimi tre tratti:** quelli sono pieni, tutto il resto è spento allo
    stesso modo. Serve perché il cammino può incrociarsi — due righe che si accavallano sono
    altrimenti indistinguibili, e non si sa quale delle due è quella da cui tornare indietro. La
    coda è corta di proposito: sfumando su quattordici tratti la differenza fra l'uno e l'altro era
    un niente, e su un viaggio lungo la linea sembrava tutta uguale proprio dove serve guardarla.
    Quello che si legge non è «quanto è vecchio questo pezzo», che non serve a nessuno, ma «da dove
    sono appena arrivato», che è l'unica domanda che si fa la mano.

    **Il riempimento va dritto, o non riempie.** Quando la mano corre e salta un esagono o due, il
    buco si chiude tirando una linea: ogni passo deve avvicinarsi alla meta di quasi un esagono
    intero. Prima qui c'era un cammino vero, con lo stesso Dijkstra del server, e sembrava la scelta
    più generosa — qualunque buco si poteva chiudere. Il risultato era che avvicinando il mouse a un
    fiume la freccia non ci sbatteva contro: se ne andava a cercare il ponte tre esagoni più in là,
    e ti ritrovavi addosso una strada che non avevi disegnato e che toccava disfare a mano. Adesso
    si ferma e lo dice. Il giro lungo esiste ancora, ma lo decide chi gioca portandoci il mouse
    sopra un esagono alla volta.

    Lo stesso vale per il **primo** passo del trascinamento, che ha una scorciatoia sua: la mano che
    punta lontano chiede la via più corta fin lì, e la ottiene — è il senso di «premi e hai la
    strada», e quella strada usa **ponti, guadi e tutto il resto**, perché è la stessa che
    calcolerebbe il tasto destro. Ma se il primo movimento è il passo **accanto**, vale la regola
    della guida a mano: un esagono, o niente. Senza questa distinzione bastava il primo centimetro
    di trascinamento verso un fiume per vedersi disegnare il giro.

    Il confine fra i due gesti sta fra le prime due corone di esagoni: i sei vicini stanno a un
    passo, la corona dopo a 1,73 passi in su. Dentro la prima corona stai disegnando; fuori stai
    indicando un posto.

    **Il ponte non sparisce mai dai conti.** Questa regola riguarda solo chi *disegna* la strada a
    mano: il campo dei costi che il browser riceve, la rotta del tasto destro, il piano che il
    server ricalcola quando lasci il tasto e il cammino di un viaggio già partito continuano tutti a
    passare dai ponti e dai guadi come prima. Quello che non succede più è che la freccia ti
    *porti* a un ponte lontano mentre stai disegnando un passo alla volta.

    Il conto lo fa il server una volta sola, quando scegli chi parte: mentre trascini non parte
    nessuna richiesta, così la freccia sta dietro alla mano anche su una partita in rete. Il
    cammino disegnato viene comunque ricontrollato dal server — deve partire da dove sta il
    gruppo, procedere di esagono in esagono senza salti e non attraversare terreni impraticabili
    — e i costi li ricalcola lui: del conto fatto dal browser non si tiene niente.
  * oppure **tasto destro** sull'esagono di destinazione, che prende sempre la via più
    economica in un colpo solo.

  Tenere premuto il tasto destro sposta la mappa come sempre, e lo puoi fare **mentre stai
  ancora trascinando col sinistro**: è il modo di allungare un viaggio oltre il bordo dello
  schermo senza mollare la freccia.

  Il trascinamento sostituisce sempre la freccia di prima: appena ricominci a tirarne una, la
  vecchia sparisce, così non ci sono due percorsi sullo schermo e non si sa quale valga.

  **Quando la freccia non va avanti, lo dice.** Prima si fermava e basta: la mano continuava a
  muoversi e sullo schermo non succedeva niente, che è il modo migliore per far credere che l'app
  si sia impiantata. Adesso lo dice in tre modi insieme, perché uno solo si perde: la freccia
  **lampeggia rossa** per mezzo secondo, il telefono **vibra** (sul portatile non succede niente:
  è una delle tre vie proprio per questo) e in alto a destra compare **il perché**. I due perché
  sono diversi e vanno distinti: *fra i due esagoni c'è acqua* — e allora ci vuole un ponte, un
  guado o una barca — oppure *la mano è saltata troppo in là*, e la strada esiste ma è un giro
  lungo che nessuno ha chiesto di fare. L'avviso scritto compare al massimo una volta ogni due
  secondi e mezzo: contro un fiume la mano ci sbatte venti volte al secondo, e venti avvisi
  sarebbero peggio del silenzio. **Contro l'acqua il lampo è immediato**: la sosta che la freccia
  fa prima di entrare in una cella serve a non entrarci per un tremolio, non a ritardare un no —
  se la cella indicata è l'esagono accanto o l'altra sponda di questo, e fra i due non si passa,
  lampeggia subito. E «accanto» lo dice la bussola della griglia, non la distanza fra i punti:
  da quando ogni sponda ha il punto del suo pezzo, due sponde dello stesso esagono possono stare a
  mezzo esagono l'una dall'altra, e il conto sulla distanza le prendeva per lontane. **Premere dove
  non si arriva lo dice** come il tasto destro — «Nessun percorso» — invece di restare muto.

  **Il lampo rosso lo vede anche chi guarda.** Quando la freccia di qualcuno sbatte contro un
  fiume, diventa rossa su tutte le mappe, non solo sulla sua. L'avviso scritto e la vibrazione
  restano a chi ha in mano il mouse — un messaggio per ogni sbandata di un altro sarebbe solo
  fastidio — ma *che* di lì non si passi è esattamente la cosa di cui il tavolo sta parlando in
  quel momento, e va vista da tutti. Il rosso si spegne da sé dopo mezzo secondo, anche se chi
  disegna resta fermo lì contro.

  **La freccia la vedono tutti mentre la tiri.** Prima era un fatto privato — gli altri vedevano il
  viaggio solo a cose fatte — e al tavolo voleva dire discutere una rotta guardando una mappa ferma.
  Adesso mentre trascini la stessa strada compare sulle altre mappe, con **quanto costa** — le
  stesse attività e gli stessi giorni che leggi tu, non un conto rifatto altrove — e sotto **chi la
  sta disegnando**, in un **colore diverso per ogni persona** collegata (non per personaggio: al
  tavolo capita spesso che uno muova il gruppo di un altro, e la domanda a cui serve rispondere è
  «di chi è questa freccia»). Lo stesso colore lo vedi anche tu sulla tua, o non la riconosceresti
  fra le altre.

  Vale per **tutti** i modi di scegliere una meta, non solo per il trascinamento: anche il tasto
  destro, e il piano che il server rifà quando molli il righello, arrivano agli altri — con «*sta
  preparando*» invece di «*sta tracciando*», che è la differenza fra una mano in movimento e un
  viaggio pronto da confermare. Resta lì finché chi l'ha fatto non lo cambia, e sparisce quando
  parte, quando viene annullato, e quando chi l'aveva in mano esce dalla modalità Viaggio: un
  piano che nessuno sta più guardando non deve restare sulla mappa di nessun altro.

  E non compare a chi sta facendo altro: se stai tracciando fiumi o stendendo la nebbia, le
  frecce degli altri non ti arrivano. Stai guardando la mappa per un'altra ragione, e una rotta
  in mezzo al disegno è solo qualcosa davanti.

  Chi la vede segue la stessa regola delle rotte già partite: il GM tutte, un giocatore quelle di
  gente di cui sa dov'è. E viaggia come una fila di esagoni, non come un disegno — poche decine di
  byte a movimento — perché la calibrazione della griglia ce l'hanno già tutte le finestre.

  **Si può viaggiare anche verso l'ignoto.** Gli esagoni dove il gruppo non è mai stato non
  fermano il pianificatore: contano come il terreno peggiore (difficile superiore, 3 attività),
  e il piano lo dice in chiaro — *«tanti esagoni del percorso non sono mai stati esplorati:
  contati al costo peggiore. Il viaggio vero può solo essere più breve di così»*. La freccia
  scrive **max** davanti al totale per ricordare che quello è un tetto, non una misura.

  Il costo è lo stesso per ogni esagono ignoto, quindi non racconta niente di cosa ci sia
  dentro: la nebbia resta nebbia, e anche una categoria decisa dal GM su un esagono nascosto
  non entra nel conto del giocatore. Restano invalicabili solo i terreni a cui la wiki non
  assegna una categoria (lago, fiume, rovine): quelli il GM li decide a mano.

* **dal riquadro Viaggio**, a destra: scegli chi parte da un elenco, clicca la destinazione e
  premi *Calcola il percorso*. La freccina accanto a quell'elenco **toglie dalla mappa** i
  personaggi scelti: niente esagono, niente veicolo, tornano nella scheda Compagnia da rimettere
  sulla mappa. È la via d'uscita quando un segnalino finisce dove nessun viaggio parte; chi è
  in viaggio non viene mosso.

**Parti** mette il gruppo in cammino: da lì avanza da solo mentre il tempo scorre. **Applica e
sposta** salta al risultato, per quando al tavolo non serve far passare i giorni. In entrambi i
casi il piano si congela alla partenza — costo di ogni tappa e attività al giorno restano quelli
di allora — così un viaggio già cominciato non cambia sotto i piedi se il GM ritocca il terreno
a metà strada.

**Viaggio.** Sotto i dettagli dell'esagono c'è il riquadro *Viaggio*: scegli chi parte, clicca
sulla mappa l'esagono di destinazione e premi *Calcola il percorso*. L'app cerca il cammino più
economico e mostra, esagono per esagono, terreno, categoria, strade e attività spese, più il
totale, le attività al giorno e i **giorni stimati**. Il percorso resta evidenziato sulla mappa.

Le regole sono quelle dell'[Esplorazione degli Esagoni](https://pf2.altervista.org/wiki/Esplorazione_degli_Esagoni),
trascritte in `rules/data/kingdom.json`:

| | |
|---|---|
| Costo di *Viaggiare* | terreno aperto 1 attività, difficile 2, difficile superiore 3 |
| Esagono mai esplorato | contato al costo peggiore (3): stima al massimo, non misura |
| Dove si paga | sull'esagono in cui si **entra** |
| Strade | migliorano il terreno di un grado |
| Attività al giorno | fino a 3 m ½ · 4,5–7,5 m 1 · 9–12 m 2 · 13,5–16,5 m 3 · 18 m o più 4 |
| Velocità del gruppo | quella del membro più lento |
| Marcia forzata | +1 attività di *Viaggiare*, per giorni pari al modificatore di Costituzione (minimo 1); oltre, Affaticato |
| Velocità di Viaggio | 3 m → 1,8 km/h · 14,4 km al giorno, e così via fino a 18 m → 10,8 km/h · 86,4 km al giorno |

**Attività e chilometri sono due tabelle diverse, e conviene non confonderle.** Il viaggio fra
esagoni si conta in *attività al giorno*: un esagono è una giornata e mezza di cammino, e i
chilometri non entrano nel conto. La **Tabella Velocità di Viaggio** risponde all'altra domanda —
«quanto andiamo veloci» — e l'app la mostra sotto il piano, accanto alla Velocità del gruppo:
*«il più lento del gruppo: Argyon su «carro» 12 m — 7,2 km/h · 57,6 km al giorno»*.

Le nove righe della tabella sono trascritte dalla wiki. Per le Velocità che la tabella salta —
13,5 e 16,5 metri — e per un veicolo più svelto di 18 metri, si continua con la proporzione della
tabella stessa: **0,6 km all'ora per ogni metro di Velocità**, che è il fattore che riproduce
esatte tutte e nove le righe scritte, dalla prima all'ultima. (Nella tabella in piedi si legge
come «ogni tre metri in più, un miglio all'ora in più».) Non è una regola aggiunta: è la regola
della tabella, estesa dove la tabella si ferma, e nei dati è marcata come tale.

Quelle distanze valgono su terreno piano e sgombro: **il terreno difficile le dimezza**, il
superiore le riduce a un terzo. E se il viaggio chiede una prova — nuotare un fiume, scalare una
parete — la wiki lascia al GM una prova **una volta all'ora**, da leggere su questa stessa
tabella. L'app lo ricorda dove serve e non tira niente al posto suo.

Due cose che l'app **non** indovina:

* **La foresta**, che la wiki dà come «difficile o difficile superiore», viene contata come
  difficile con un avviso in chiaro. Per ogni altro terreno che la wiki non classifica il piano
  si ferma, elenca gli esagoni interessati e dice perché; la categoria la decide il GM, esagono
  per esagono, dal riquadro *Regia*.
* **Le rovine.** La wiki non gli assegna una categoria di viaggio: il tavolo ha scelto la più
  dura, *terreno difficile superiore*. Nei dati la voce porta `"source": "table"` e il piano lo
  dice ogni volta che quella categoria entra nel conto.
* **L'acqua fra due esagoni.** Vedi *Confini d'acqua* qui sotto: le regole conoscono i Confini
  d'Acqua e i Ponti dentro un insediamento, non fra gli esagoni della mappa. Portarli lì è una
  scelta del tavolo.
* **Trappola o Pericolo, Dungeon, Evento.** Tre Elementi del Terreno che la wiki non ha: non
  hanno nessuna meccanica e non toccano né il regno né il viaggio. Sono segnaposti che il Game
  Master usa per tenere in ordine la mappa — dove sta un pericolo, dove si entra in un posto da
  esplorare, dove deve succedere qualcosa — e come tutto il resto si possono tenere segreti e
  rivelare quando il gruppo li trova. Nei dati portano `"source": "table"`, nei menu e nel
  Manuale sono marcati «del tavolo»: sono lì per non stare su un foglio a parte, non per essere
  scambiati per regole.
* **I veicoli.** Che un veicolo sostituisca la Velocità del gruppo nell'Esplorazione degli
  Esagoni la wiki non lo scrive: è una lettura del tavolo, e l'app lo segnala ogni volta che
  usa la Velocità di un veicolo al posto di quella a piedi. Che un **passeggero** si muova alla
  Velocità del veicolo è una seconda lettura, ancora più larga della prima: per questo «Salgono
  tutti a bordo» è un interruttore spento e non il comportamento normale, e per questo l'avviso
  che compare quando è acceso lo dice a chiare lettere.

#### Confini d'acqua, guadi e ponti

Un fiume non sta *in* un esagono: sta **fra** due esagoni, e quali due dipende da come è
disegnato. Per questo i confini sono l'unica cosa della mappa che non è una proprietà della
cella: stanno su un **lato**, e valgono da tutti e due i versi.

| Confine | Cosa fa |
|---|---|
| *(non segnato)* | terra: si passa e non costa niente. È il caso normale |
| 🌊 Confine d'Acqua | non si passa, se non a bordo di un veicolo d'acqua |
| 〰️ Guado | si passa, ma costa un'attività di *Viaggiare* in più |
| 🌉 Ponte | si passa senza costo aggiuntivo |

**Non è una regola della wiki.** Le regole conoscono i Confini d'Acqua e la struttura Ponte
sulla *Griglia Urbana* di un insediamento — «i ponti possono essere costruiti solo sui Confini
d'Acqua» — ma non dicono niente sui lati fra gli esagoni della mappa. Il vocabolario è quello del
gioco, la regola di viaggio no: nei dati il blocco porta `"source": "table"`. È cosa diversa
dall'Elemento del Terreno **Ponte**, che sta su un esagono e riguarda il costo in PR di
*Costruire Strade*: quello viene dalla wiki, questo no.

Laghi e fiumi **non sono terreni**: si disegnano sopra il terreno nella modalità Acque, e per
il viaggio conta solo l'acqua disegnata. Un esagono sotto un lago tiene il suo terreno; un
salvataggio che segnava esagoni come Lago o Fiume perde quei segni al primo avvio.

#### Le rive: un fiume taglia l'esagono, non lo chiude

Un fiume che *attraversa* un esagono è una cosa diversa da un fiume che ne segna il confine. Non è
che «lì non si passa»: ci si passa benissimo, si cammina lungo la riva da un esagono al successivo.
Quello che non si può fare è **saltare da una sponda all'altra** senza un ponte. Seguendo la strada
lungo il fiume si va avanti; provando ad andare di sopra o di sotto, no — e da che parte ti trovi
dipende da dove sei entrato.

L'app lo modella dividendo l'esagono in **rive**: i suoi sei lati si raggruppano in due (o tre, a
una confluenza), e da una riva si esce solo dai lati che le appartengono. Per il pathfinder un
esagono tagliato non è un nodo ma due, e la riva su cui stai non è una cosa che ti porti dietro —
è il posto in cui sei. La differenza conta: se «da che parte sono» fosse una proprietà del
viaggiatore, il costo per arrivare da qualche parte dipenderebbe da come ci sei arrivato, e
Dijkstra darebbe risposte sbagliate senza accorgersene.

**Fuori dall'algoritmo un esagono resta due coordinate**, come è giusto: «17,5» è come lo chiami
tu, e le rive non compaiono da nessuna parte nei menu. Dove si vedono è **sulla mappa**, ed è una
cosa sola detta bene: ogni sponda è il **pezzo di esagono** che le tocca, e ha un suo punto — il
baricentro di quel pezzo, tirato appena verso il centro per non stare addosso alla riga dell'acqua.

Dove l'acqua entra da **più di due parti** non c'è nessuna corda: i tratti si tirano tutti al
centro, e ogni pezzo è un cuneo che dal centro si apre verso i suoi lati — il centro fa parte della
sua forma, altrimenti una fetta di un lato solo non avrebbe area e il suo punto ripiegherebbe in
mezzo all'esagono, cioè proprio dove quella fetta non è. E quando l'acqua corre **lungo** un lato il
pezzo che resta di qua è una striscia larga zero: un'area non c'è e un baricentro nemmeno, ma un
*dove* sì, ed è il punto di mezzo di quel lato.

Quel punto è la differenza fra una sponda che si vede e una che si può *indicare*. Ci stanno dentro
i segnalini di chi è su quella riva (più piccoli, perché mezzo esagono è metà dello spazio), ci sta
il tondo dei mezzi ormeggiati lì (scostato verso il bordo, dalla parte opposta all'acqua, o
coprirebbe le facce), e ci passa la freccia del viaggio — che comincia da dove stanno i segnalini,
non dal centro dell'esagono, così si vede che è la strada di quel gruppo lì.

Prima le due rive stavano tutte e due nel centro dell'esagono. Si vedeva male e si *usava* peggio:
il mouse non aveva modo di dire quale delle due stesse indicando, e per passare un ponte bisognava
azzeccarne l'icona. Adesso basta portare il puntatore nell'altra metà dell'esagono — il confine fra
le due è la riga del fiume, non un pixel — e la freccia ci entra.

Un **ponte** ricuce le due rive: l'esagono torna a essere uno solo, e ci si taglia dritto. Sulla
mappa quel passaggio è il **gomito** della freccia: entra nella sponda di qua, piega, ed esce da
quella di là. È l'unico posto dove il disegno del viaggio ha un punto in più degli esagoni che
attraversa, e c'è una ragione: un ponte non è una tappa, è come si è passati.

**Chi naviga.** Nei *Trasporti* ogni veicolo va di terra, d'acqua o in volo. Un gruppo attraversa
l'acqua se ha con sé un mezzo che la passa — d'acqua o volante — disponibile, con posti per tutti,
**e** con «Salgono tutti a bordo» acceso: salire su una barca è una decisione del tavolo, non
qualcosa che l'app fa da sé perché accorcia il percorso. Oppure a nuoto, se ce l'hanno tutti: la
wiki mette la Velocità di Nuotare accanto al veicolo come secondo modo di passare, e lì non c'è
niente su cui salire.

#### La modalità Acque

Il pulsante **Acque**, accanto a *Viaggio* sopra la mappa, apre una modalità con il suo riquadro
sulla destra — come fa *Viaggio* — e dentro c'è tutto quello che serve: i pennelli, il colore
dell'acqua, la lettura automatica e la pulizia. Sta tutto lì apposta: prima metà era in una barra
sopra la mappa e metà nella scheda Regia, e per usarlo bisognava sapere che erano la stessa cosa.

Come per *Viaggio*, **l'icona del pulsante è un interruttore a sé**: cliccando la goccia (non il
resto del pulsante) i confini già segnati si nascondono e l'icona si sbarra, senza uscire dalla
modalità. Serve a guardare il disegno sotto senza le righe azzurre sopra.

**Disegnare l'acqua.** Il pennello *Acqua* si usa unendo **due vertici dello stesso esagono**:
dove l'acqua entra e dove esce. Se i due vertici sono vicini nel giro, la corda fra loro *è* un
lato dell'esagono e ne esce un Confine d'Acqua; se sono lontani la corda lo attraversa e ne esce un
taglio fra due sponde. È un gesto solo perché è una cosa sola — un fiume si disegna unendo punti, e
che corra sul bordo o in mezzo lo dice il disegno, non un pulsante diverso.

**E i tre pennelli si usano tutti così.** *Acqua*, *Ponte* e *Guado* sono lo stesso gesto: due
vertici dello stesso esagono. Quello che cambia è la linea che ne esce, non come si disegna — con
l'Acqua è il fiume, col Ponte e col Guado è il modo di passarlo. Prima il Ponte e il Guado si
usavano cliccando una linea già disegnata: due gesti diversi per una cosa sola, e la differenza non
stava nel disegno ma solo in come era venuto il codice.

| Pennello | Due vertici vicini (un lato) | Due vertici lontani (in mezzo) |
|---|---|---|
| *Acqua* | Confine d'Acqua fra i due esagoni | il fiume che taglia l'esagono in due sponde |
| *Ponte* | Ponte su quel bordo | Ponte di traverso al fiume, da una sponda all'altra |
| *Guado* | Guado su quel bordo | Guado sul fiume, da una sponda all'altra |

**Vale anche il centro dell'esagono**, ed è un punto come gli altri. Serve a far girare un fiume
dentro una cella invece di tagliarla dritta: vertice, centro, vertice. Prima il centro compariva da
solo — quando un esagono finiva con più di due sponde i tratti si tiravano tutti lì in mezzo — e dal
di fuori sembrava che la linea si agganciasse a caso. Ora è una scelta.

Il centro **non divide**, e il motivo è la regola generale: le sponde di un esagono sono gli **archi
di bordo compresi fra due punti in cui una linea tocca il bordo**. Il centro il bordo non lo tocca,
quindi non taglia. Un tratto che entra e si ferma in mezzo lascia l'esagono intero — il fiume c'è, ma
di là si passa ancora — e l'app te lo dice invece di far finta di niente. Chiudendolo fino a un altro
vertice, l'esagono si divide.

Da qui in poi il disegno del fiume **si tiene**, e non si ricostruisce dalle sponde: passare per il
centro o andare dritti da un vertice all'altro divide l'esagono allo stesso modo, e quale delle due
hai tirato lo sa solo il disegno. Anche la barca lo segue, e la Gomma toglie **un tratto alla volta**:
se un fiume l'hai fatto in tre pezzi, sbagliarne uno non ti costa tutti e tre.

**Su quale esagono stai disegnando lo dicono i due vertici insieme**, non il primo clic. Ogni clic
prende solo il vertice più vicino della griglia — quello che indichi, non quello dell'esagono in cui
è caduto il puntatore — e l'esagono è quello che ce li ha tutti e due: uno solo se i vertici sono
lontani, due se sono vicini, ma allora la corda fra loro è il lato che si dividono ed è lo stesso da
entrambe le parti.

Serve perché un vertice appartiene a **tre** esagoni: cliccandolo preciso, «in che esagono sono?» dà
la risposta sbagliata quattro volte su sei. Finché era il primo clic a fissare l'esagono, il secondo
vertice veniva cercato fra quelli della cella sbagliata, e ne usciva un tratto diverso da quello
indicato — su 480 coppie di vertici cliccati esatti, ora ne sbagliano zero.

Il vertice preso si vede come un **pallino arancione**, e gli esagoni ancora in ballo — quelli che
se lo dividono, e fra cui sceglierà il secondo clic — si **contornano di arancione** sulla mappa:
così si vede prima di disegnare, non dopo.

Quel mezzo tratto **se ne va con la modalità**: spegnendo le Acque, cambiando pennello o passando
al Viaggio, il pallino e i contorni spariscono. Prima restavano disegnati — spegnevi le Acque per
andare a leggere un esagono e ti trovavi addosso un segno arancione che non voleva più dire
niente, e l'unico modo di toglierlo era passare dal Viaggio, che per caso era la sola strada che
lo azzerava. Restando invece dentro le Acque il tratto resta in mano, che è il punto: hai cliccato
un vertice e stai per cliccare il secondo.

Il secondo clic è tollerante ma non troppo: fra i vertici lì intorno vale il più vicino **che vada
d'accordo col primo**, purché stia entro un raggio ragionevole dal punto cliccato. Oltre quello non
disegna niente e dice perché. Prendere comunque il compatibile più vicino, per lontano che fosse,
voleva dire che una mano fuori bersaglio otteneva lo stesso un tratto — un altro, su un altro
esagono. Due volte lo stesso vertice annulla, e due vertici che non si dividono nessun esagono non
disegnano niente.

Un secondo taglio **si somma** al primo invece di sostituirlo: due corsi d'acqua che attraversano lo
stesso esagono lo dividono in quattro sponde, non in due.

**Ponte.** Un attraversamento può stare in due posti, e su una mappa vera sta quasi sempre nel
secondo: sul **bordo** fra due esagoni, oppure sul **fiume che ne attraversa uno**. Quale dei due
intendevi lo dice il clic: **si clicca la riga d'acqua da scavalcare** — un tratto dentro
l'esagono o un lato bagnato fra due — e il ponte si posa lì; sul taglio si vede come un varco di
traverso al fiume con il glifo 🌉: da lì in poi le due sponde si parlano. Il gesto a due vertici è
**solo dell'Acqua**: col Ponte o col Guado in mano un clic fuori dall'acqua non prende nessun
vertice e non accende nessun contorno, dice solo di cliccare l'acqua. (Restava acceso come ripiego,
e un clic a vuoto prendeva un «primo vertice» che non voleva dire niente: il codice di quel ripiego
non c'è più.)

Un ponte scavalca qualcosa, quindi il fiume dev'esserci già: su un esagono asciutto il pennello non
scrive niente e lo dice. E se i due vertici cadono dalla stessa parte dell'acqua non c'è niente di
attraversato — anche lì si ferma invece di indovinare.

Solo una **barca** cambia il righello, e vale la pena dirlo: la sua strada è l'acqua disegnata,
quindi il campo che il browser riceve è un altro. Un carro no — cambia la Velocità, non la strada —
e il campo di terra la sa già, perché chi è a bordo se lo porta scritto addosso. Chiedendo il campo
d'acqua per qualunque mezzo, con un carro in mano al righello arrivava roba d'acqua: sulla terra
asciutta non c'è niente da seguire, e trascinare non disegnava più niente.

Un ponte interno **non costa attività**: l'esagono l'hai già pagato entrandoci, e attraversarlo
resta un attraversamento solo.

Ed è proprio questa riga che il righello del browser aveva letto male. Il suo conto di un passo era
«l'esagono in cui entri, più quello che costa il lato» — vero fra due esagoni, falso fra le due
sponde dello stesso: lì non entri in nessun esagono nuovo, e paghi solo l'attraversamento, che per
un ponte è zero. Con un conto diverso da quello del server, la freccia che il browser ricostruisce
mentre trascini arrivava al ponte e non trovava più da dove venire: si fermava lì. Tenendo premuto
il tasto si vedeva solo il pezzo **dopo** il ponte, e il resto compariva soltanto lasciandolo —
quando risponde il server, che il ponte lo conta giusto. Adesso il conto di un passo sta in un posto
solo (`stepCost`) e lo usano tutti e quattro i mestieri del righello: il campo all'indietro, il
cammino a ritroso, la guida tirata a mano e il costo mostrato.

Il ponte non è scritto come «fra la sponda 1 e la 2» ma come **fra due lati** dell'esagono. Il
motivo è che i numeri delle sponde li rimescola il primo taglio nuovo, mentre «la sponda che ha il
lato 2» è una domanda che ha sempre la stessa risposta: un secondo fiume può dividere ancora
l'esagono, e il ponte continua a unire quello che univa.

**Guado.** Stesso gesto, e vale nei due posti: sul **bordo** costa un'attività in più;
sul **fiume che attraversa un esagono** costa quanto costa quel terreno — in pianura un'attività,
in palude tre. Non è una riga della wiki, che il guado di un fiume dentro un esagono non lo prezza,
ma non è nemmeno un numero inventato: è l'unico già scritto per quel posto, ed è la scelta del
tavolo. Il GM può deciderne un altro sul singolo guado, dalla scheda dell'esagono (*Confini del
terreno* → *Sul fiume che attraversa l'esagono*), dove trova anche il promemoria che per un tratto
da nuotare o da scalare le regole gli lasciano una prova di **Atletica una volta all'ora**.

Sul disegno il guado è **una riga puntinata lungo l'acqua**, chiara, sul pezzo di fiume in cui si
guada — la stessa lingua del guado sul bordo fra due esagoni. Niente di traverso: la traversa e il
glifo sono del ponte, e sul guado una tacca di traverso sembrava una fasciatura sul fiume invece di
un punto in cui si passa. Nel dettaglio per esagono il guado compare come 〰️
con la sua attività in più, il ponte come 🌉, e il piano lo scrive fra gli avvisi: quello che paghi
si vede da dove viene.

**Cancellare.** Il pennello *Gomma* si usa **tenendo premuto e passando sopra le linee**: sparisce
quella su cui passi — un confine, un taglio, o un ponte sul taglio. Un clic solo toglie la linea
sotto il puntatore. Sopra un ponte vince il ponte, che è quello che sta sopra: altrimenti non ci
sarebbe modo di toglierlo senza portarsi via anche il fiume. Cancellando il fiume, invece, se ne
vanno anche i ponti che lo scavalcavano: resterebbero ponti sul niente.
Prende **una linea alla volta**, la più vicina al punto: su un vertice ne convergono fino a sei, e
prenderle tutte vorrebbe dire che sfiorare un incrocio cancella mezzo fiume.

**Cancella tutta l'acqua** azzera tutto, con una conferma che dice quanto perdi e quanto di quello
era segnato a mano. Non serve per rifare la lettura automatica: quella sostituisce da sola ciò che
aveva trovato lei.

Come in *Viaggio*, mentre la modalità è accesa la colonna di destra è solo del riquadro: la scheda
dell'esagono torna quando la spegni, ed è lì — sotto *Confini del terreno* — che trovi i sei lati
con la direzione, le coordinate del vicino e una tendina per ciascuno, se ne devi correggere uno di
precisione.

**Senza niente in mano non succede niente.** In modalità *Acque* con nessun pennello acceso il clic
sulla mappa non seleziona più l'esagono: chi sta guardando i fiumi non ha chiesto la scheda di una
cella, e vedersela comparire era solo rumore.

**Una modalità alla volta.** *Nebbia*, *Viaggio* e *Acque* si prendono tutte e tre il clic sulla
mappa, quindi accenderne una spegne le altre — in tutti i versi. Quello che avevi in mano e non hai
confermato (un piano di viaggio, una proposta d'acqua, una selezione di nebbia) si scarta passando a
un'altra modalità: era una proposta, non un dato.

#### Spegnere tutto

Nel riquadro *Acque* c'è l'interruttore **«Usa i confini d'acqua»**. Spento, il viaggio torna
esattamente com'era prima: nessun fiume lo ferma, nessuna sponda lo divide. Sta al Game Master
dire al tavolo che quel fiume non si guada, come si è sempre fatto.

Se il tavolo sceglie di giocare così, conviene che il GM dia a quegli esagoni anche un terreno
normale: senza, contano come «mai esplorati» e il piano li stima al costo peggiore.

Spegnere **non cancella niente**: confini, sponde e terreni restano dove sono e tornano riaccendendo
l'interruttore.

#### Da che parte scorre: il verso della corrente

La wiki sul terreno *Fiume* dice una cosa sola ma pesante: **scendere un fiume è terreno aperto,
risalirlo è difficile o difficile superiore secondo correnti e meteo**. Per applicarla bisogna
sapere da che parte va l'acqua, e su una mappa disegnata non c'è modo di ricavarlo: è un dato in
più che qualcuno deve mettere.

Lo mette il pennello **Corrente**, e il gesto è quello che si fa col dito su una carta: clicchi il
vertice a monte, segui il fiume col mouse — la guida ti mostra il cammino, tratto per tratto,
mentre lo muovi — e clicchi dove l'acqua arriva. Tutti i tratti in mezzo prendono il verso, da
monte a valle, con una freccia verde acqua ciascuno.

Il verso **è** l'ordine dei due estremi del tratto: monte prima, valle poi. Chi ci passa confronta
il verso in cui sta andando con quello scritto — se combaciano scende, se sono opposti risale. Non
serve altro, e ripassare un fiume all'incontrario lo gira: è il gesto con cui si corregge un corso
d'acqua segnato al rovescio, e l'app ti dice quanti tratti ha girato.

**Per togliere un verso solo c'è «Togli un verso»**, accanto al conteggio dei tratti: acceso, ogni
clic toglie il verso al tratto che gli sta sotto e la riga resta dov'è. Resta in mano finché non lo
spegni — i versi sbagliati vengono a mazzi, un fiume tracciato al contrario — e si posa da sé quando
l'ultimo verso se n'è andato, perché il suo pulsante sparisce col conteggio e una gomma che non si
può posare non va lasciata in mano. Il cursore diventa quello della gomma: cosa sta per fare il clic
si vede prima di farlo.

Lo stesso lo fa **il ctrl premuto**, senza accendere niente. Era nato così, ed era l'unica strada:
una scorciatoia da tastiera che non compare da nessuna parte, però, per chi la usa non esiste — nel
riquadro si leggeva solo «Togli tutti i versi», e sembrava che per correggerne uno si dovesse
rifarli tutti. Prima ancora, l'unico modo era cancellare il fiume e ridisegnarlo: come strappare una
pagina per correggere una parola.

Un tratto **senza** verso non è un errore, e non è nemmeno un fiume ignoto: è **acqua senza
corrente**. Non c'è niente da assecondare e niente da risalire, si percorre nei due sensi allo
stesso modo e vale terreno aperto — la riga generale della wiki, «Se voli o viaggi sull'acqua, quasi
tutti gli esagoni sono terreno aperto». È il caso di tutte le righe di un lago, ed è la scelta del
tavolo per un fiume di cui il verso non è stato ancora segnato: segnare la corrente non accorcia il
viaggio, rende più caro **risalirlo**.

Perché il cammino si veda **mentre** lo disegni, il server manda al browser la rete una volta sola
— i punti e i tratti che li uniscono — e il browser fa solo il disegno. Quando clicchi, il cammino
lo rifà il server sulla sua rete: di quello calcolato di là non si tiene niente, come per il
righello dei viaggi.

#### I laghi

Un lago è una **forma disegnata a mano**. Col pennello *Lago* clicchi i vertici del contorno, uno
dopo l'altro, e torni sul primo per chiudere: il primo punto si vede più grande, ed è quello da
ricliccare. Dentro ci finiscono gli esagoni il cui centro cade nella forma — **o sul suo contorno**:
i punti che clicchi sono vertici e centri di esagono, quindi una forma tirata da un centro a un
vertice all'altro centro passa proprio sopra i due centri, e mezzo esagono su quattro vertici di fila
ha il centro esattamente sulla corda che lo chiude. Prima quei centri cadevano fuori o dentro a
seconda degli arrotondamenti, e una forma chiusa e sensata poteva «non contenere nessun esagono».

Il primo tentativo lo riempiva per allagamento — clicchi dentro e si espande fin dove le righe non
lasciano passare — e non funzionava, per un motivo che si vede subito su una mappa vera: un lago
disegnato a mano **non segue i bordi degli esagoni**, taglia dove taglia l'acqua. Quindi l'anello di
righe quasi mai chiude, e il secchiello usciva dalla mappa ogni volta. La forma la dai tu.

**La barca si sposta con chi ci sta sopra.** Un carro non ha una posizione sua — sta dove sta chi se
lo porta dietro, e il segnalino lo si disegna lì — ma una barca ce l'ha, perché è in mezzo al fiume e
ci resta anche quando l'equipaggio scende. Quando un viaggio finisce, o quando un giorno lo fa
avanzare, i veicoli **già sulla mappa** che portano quei personaggi vanno con loro; e se il viaggio è
della barca, la barca si sposta anche senza nessuno a bordo. Un carro, che sulla mappa non c'è, non
ci compare per sbaglio.

Nel riquadro *Acque* i laghi stanno tutti elencati, ognuno col suo nome, i suoi punti e i suoi
esagoni. *Modifica* rimette in mano il contorno di quello che scegli, così si aggiusta invece di
rifarlo: una forma disegnata a mano si sbaglia, e se non si vede com'è fatta non si capisce perché
il viaggio passa di lì invece che di là.

Serve al viaggio, e cambia proprio la regola. Dentro un lago **non c'è corrente** da assecondare o
da risalire: non c'è un verso, si va dove si vuole al costo del terreno aperto — che è la riga
generale della wiki, «Se voli o viaggi sull'acqua, quasi tutti gli esagoni sono terreno aperto». Si
esce dove il lago tocca un fiume, e da lì valgono di nuovo il verso e la corrente.

**Dentro si naviga davvero, non solo lungo la riva.** Il primo lago era un fiume a forma di anello:
si poteva girargli attorno e basta, che è l'esatto contrario di uno specchio d'acqua. Adesso ogni
punto della griglia che cade dentro la forma — gli angoli degli esagoni **e i loro centri** — è un
punto d'acqua, e quelli vicini sono uniti fra loro. Su questa griglia il lato di un esagono e il
raggio dal centro a un angolo sono lunghi uguali, quindi ne esce una **maglia triangolare** che
copre tutto il lago: dalla riva si arriva al centro, dal centro all'altra sponda, e ogni passo costa
mezzo esagono di terreno aperto, come tutti gli altri tratti corti.

Si uniscono i vicini, non tutti con tutti. Unire ogni punto a ogni altro darebbe una barca che
attraversa un lago intero al prezzo di un passo corto — la distanza sparirebbe. Vicino a vicino ci
si va dove si vuole lo stesso, ed è uno specchio d'acqua, non un labirinto.

**Questa maglia non si disegna.** Un lago si vede dalla sua velatura azzurra, e riempirlo di righe lo
farebbe sembrare una ragnatela: i tratti ci sono solo per la freccia del viaggio. Nemmeno il
pennello *Corrente* li trova, perché un lago non ha un verso e agganciare righe invisibili sarebbe
solo un modo di segnare per sbaglio.

Il lago non apre una strada che non c'era: l'anello di righe è acqua anche senza, e una barca poteva
già costeggiarlo. Quello che aggiunge è il **dentro**.

#### I mezzi stanno sulla mappa

Prima valeva per metà: una barca la si metteva in acqua e ci si andava, un carro lo si assegnava da
una tendina e lui compariva accanto al padrone ovunque fosse. Comodo da scrivere, e falso da
giocare — nessuno sale su una carrozza che sta a tre esagoni di distanza, e di un mezzo che non è
da nessuna parte non si può nemmeno dire dove si scende.

Adesso è una regola sola, e vale per tutti: **un veicolo sta in un esagono, e ci si sale stando lì.**

**Un mezzo si prende cliccandolo sulla mappa**, com'è per un personaggio: c'era anche un pulsante
*Viaggia con questo / Lascialo* nell'elenco, e due strade per la stessa cosa erano una di troppo —
quella col pulsante era la meno ovvia delle due. Nell'elenco resta una targhetta *in viaggio* su
quello che hai in mano.

Nel riquadro *Viaggio* c'è l'elenco **Mezzi**, tutti quanti. *Mettilo sulla mappa* e poi clicchi
dove: una barca vuole un esagono con dell'acqua disegnata o dentro un lago — su un prato l'app si
rifiuta, invece di lasciarti una barca da cui non parte nessuna rotta — un carro vuole della terra,
e chi vola sta dovunque. *Spostalo* lo muove, l'icona di ritorno lo **rimette in rimessa**: lì non
ci sta più nessuno sopra, perché restare «su» un carro che non è da nessuna parte era esattamente
il legame fantasma da cui si viene.

**Salire.** Sotto ogni mezzo posato c'è *Chi sale*, e la tendina mostra **solo i personaggi fermi
in quell'esagono**: un elenco che offre chi sta lontano e poi rifiuta fa perdere tempo. Il
controllo si rifà comunque quando premi — una tendina non è una difesa — e se provi da lontano
l'app te lo dice in chiaro: «*Argyon sta su 16,8 e «Il Carro» su 14,8: si sale su un veicolo che si
ha davanti, non su uno lontano*». Vale anche dall'altro capo: nella scheda del personaggio il campo
*Veicolo* elenca solo i mezzi posati dove sta lui.

**Scendere da una barca si dichiara**: premi *Falli scendere* e poi clicchi l'esagono dove mettono
piede. Deve essere quello del mezzo o uno accanto — scendere è un passo, non un viaggio — e deve
essere un posto su cui si sta: da una barca si scende **a riva**, e se è in mezzo a uno specchio
d'acqua l'app lo dice e non fa scendere nessuno, portala prima al bordo. La domanda ha senso perché
l'acqua di un esagono può correre sul **bordo** fra due celle: da lì si scende di qua o di là, e
quale delle due lo sa solo chi gioca.

**Da un carro no: si scende accanto al carro.** Un mezzo di terra sta in un esagono, su una sponda
precisa, e chi ne scende mette piede lì — chiederlo voleva dire permettere di scaricare la gente in
un esagono vicino, che è una cosa che un carro fermo non fa. La **sponda** conta: dove un fiume
taglia l'esagono in due, il carro sta di qua o di là dell'acqua (gliela dà il punto esatto in cui
l'hai posato) e chi scende si ritrova dalla stessa parte, non sull'altra riva.

**Chi scende non parte più.** Il viaggio che stavi guardando era di quel gruppo su quel mezzo:
appena qualcuno ne scende non si può più fare, e resta soltanto da toglierlo di mezzo. Prima
rimaneva disegnato sulla mappa con i suoi pulsanti sotto — *Applica e sposta* e *Parti* erano lì e
non partiva niente. Adesso lo sbarco spegne la proposta insieme a sé.

E se il viaggio era **già partito**, scendere lo ferma: l'app te lo dice prima — «*Argyon è già in
cammino: scendendo, quel viaggio si annulla*» — e solo se confermi lo annulla e ti chiede dove
mettono piede. Chi era in cammino resta dov'è adesso e riparte quando vuoi. È la stessa regola di
tutto il resto: gli effetti si propongono e si confermano, mai in silenzio.

#### Viaggiare per fiume

**Cliccando la barca sulla mappa** il viaggio diventa un altro: si parte da dove sta lei, non da dove stanno i personaggi (che magari sono ancora a riva), e
il tasto destro sceglie dove arrivare. Il riepilogo parla la lingua giusta: quanti esagoni si
scendono, quanti se ne risalgono, quanti sono lago, quanti sono senza verso. Quando l'acqua non ci
porta lo dice, invece di ripiegare su un cammino a piedi che nessuno ha chiesto.

**La barca si muove di incrocio in incrocio, un lato di atomo alla volta.** Ogni riga d'acqua
disegnata è fatta di lati di atomo — quattro per una corda da parte a parte, due per un raggio dal
vertice al centro — e i punti in cui le righe si incontrano sono gli **incroci**: i sei angoli, il
centro e dodici punti interni, diciannove per esagono. La barca sta *su* un incrocio (si posa
cliccando vicino a uno, anche dove la riga che lo taglierebbe non è disegnata, purché sia
sull'acqua) e ogni passo da un incrocio al vicino costa **un quarto** di attività, **il doppio
contro corrente**; un lato dell'esagono, che è una riga sola e più lunga, costa **mezza**. Quattro
quarti sono una corda intera, cioè un'attività: lo stesso numero di chi attraversa l'esagono a
piedi, e non è scelto — esce dalla geometria. Si somma tutto lungo la rotta e si arrotonda
all'intera alla fine. **Un lago è un esagono con tutte le righe, dentro la forma disegnata**: i lati di atomo con gli
estremi dentro l'anello (o sopra) sono acqua
ferma, senza verso, e ci si ferma su ogni incrocio — fiume e lago sono lo stesso sistema.

**La freccia segue le righe**, non i centri degli esagoni. Le celle del campo che il server manda
al righello sono gli **incroci**, e vale la regola di terra: premere dà subito la via più corta
fino all'incrocio premuto, poi la mano guida da un incrocio all'altro (quelli che salta si
riempiono lungo l'acqua, se sono pochi; tornare indietro si mangia l'ultimo passo). Il tasto destro
fa la rotta più economica dall'incrocio della barca. Quella confermata è la stessa, e la rotta
partita si ridisegna sull'acqua ogni giorno, dall'incrocio su cui la barca si è fermata.

**Si sale e si scende dalle sponde che toccano l'incrocio.** Una barca ferma a un angolo è di tre
esagoni: da ogni pezzo di quei tre che tocca quel punto ci si sale, e la tendina *Chi sale* mostra
proprio quelli. Scendendo si clicca un pezzo di esagono che tocca l'incrocio — e a riva, non in
mezzo al lago. **Due barche ferme sullo stesso incrocio** sono un tondo solo col numero, come due
persone nello stesso pezzo: cliccandolo si sceglie quale, e ognuna mostra dentro chi ci viaggia.

Sotto ci sono due cose che non si vedono ma che servivano. La prima: dentro un esagono si passa da
un punto all'altro **senza pagare niente** — l'ansa che lo attraversa, il ponte che lo scavalca — e
un cammino fatto di passi a costo zero non si ripercorre all'indietro, perché «scendi finché la
distanza cala» non cala mai. Il server allora conta in millesimi e aggiunge un millesimo per passo:
fra due strade che valgono uguale vince quella con meno pezzi, e il cammino si ritrova sempre. La
seconda: il grafo dell'acqua è **orientato** dove non te lo aspetti — andando da un esagono al
successivo il passo costa, tornando indietro si finisce in uno stato diverso, stesso punto e altro
esagono — e il righello ripercorre il cammino cercando chi ce l'ha portato *fra i vicini*. Se lì ci
sono solo i posti dove si può andare, chi ci ha portati non lo trova mai.

C'è anche la via di mezzo: con una barca **assegnata a chi parte** e l'interruttore «Salgono tutti a
bordo» acceso, accanto al viaggio per terra compare **⛵ Per fiume**: gli stessi giorni contati
seguendo l'acqua disegnata, con quanti ne fai in più o in meno che via terra. Non sostituisce niente da sola — *Prendi il fiume* lo fai tu, e
*Torna via terra* ti riporta indietro. A volte il fiume è più lento e si prende lo stesso, perché
in barca non ci si stanca allo stesso modo, e quello l'app non lo sa.

**Si paga quello che si percorre, lato di atomo per lato di atomo.** Un lato di atomo vale un
quarto di esagono di strada, un lato dell'esagono mezzo. Quanto costi quel quarto o quel mezzo lo
dice il verso: a valle terreno aperto, a monte difficile, cioè il doppio. Il verso sta sulla riga
disegnata — il pennello lo scrive lì — e ogni suo pezzo lo eredita. Il terreno dell'esagono non conta — chi scende lo
Shrike non attraversa la palude, la costeggia — e i confini d'acqua non si pagano: non li stai
attraversando, ci stai navigando sopra.

Prima si pagava **l'esagono in cui si entrava**, come per il viaggio a piedi, ed era il conto
sbagliato per un motivo che si vede subito: un fiume che corre sul bordo fra due celle appartiene a
tutte e due, e non c'è modo di dire in quale sei entrato. Il costo dipendeva da come era stato
disegnato invece che da dove passa l'acqua, e con un fiume di confine nella cella accanto non ci si
arrivava affatto. Ora un tratto è una cosa sola e si misura; e percorrendo un tratto di bordo si può
restare di qua o passare di là, perché è la stessa acqua.

Mezza attività sulla scheda non esiste: quello che si paga è l'attività intera in cui quella metà
cade, e l'arrotondamento lo fanno allo stesso modo il server e la freccia trascinata — o i due
numeri non combacerebbero.

**Sull'acqua la freccia non si guida a mano.** Sulla terraferma sì, ed è voluto: puoi trascinare di
esagono in esagono e far passare il gruppo per la foresta invece che per la strada, perché lì una
strada vale l'altra. Fra due punti di un fiume no — la strada è quella. E la guida a mano avanza
*una cella alla volta*: da quando le celle sono i punti dell'acqua ce ne sono parecchie dentro lo
stesso esagono, la mano correva avanti e il passo restava indietro, e per arrivare da qualche parte
bisognava trascinare molto più in là di dove si voleva andare. Adesso la freccia rifà il cammino
fino al punto che indichi, e basta.

C'era anche un tremolio, e veniva da come la freccia sceglieva il punto da puntare. La regola era
fatta per le **rive**: dove un fiume taglia un esagono, quell'esagono ha due celle con lo stesso
centro, e il punto da solo non dice da che parte del fiume sei — lo dice da dove vieni. Su un fiume
però le celle di uno stesso esagono sono *tutti* i suoi punti d'acqua, e sceglierne una «perché
confina con quella di prima» faceva saltare la meta da un punto all'altro a ogni movimento del
mouse. Sull'acqua vince il punto più vicino al dito, e basta; fra punti che cadono esattamente nello
stesso posto — lo stesso vertice visto da due esagoni — vince il più economico, che è una scelta
stabile perché non dipende da dove viene la mano. Misurato facendo scorrere il dito lungo il fiume
in 120 passi: prima la meta cambiava 121 volte tornando indietro 28, ora cambia 3 volte e non torna
mai indietro.

E quando lasci il tasto **si ripercorre la strada che hai tirato**, non se ne rifà una più
economica. È la stessa regola del righello di terra e per lo stesso motivo: chi ha seguito il fiume
col dito non vuole vedersi sostituire la strada da un'altra che costa un'ora di meno. Il browser
manda tutta la strada punto per punto — il punto dice *quale* punto d'acqua, l'esagono dice *da che
parte* si era, e servono tutti e due perché uno stesso vertice appartiene a più esagoni — e il
server la ripercorre un passo alla volta controllando che ogni passo esista davvero. Se non regge,
allora sì, ripiega sulla più economica.

**Il tasto destro si aggancia all'acqua più vicina**, entro poco più di un esagono. Prima pretendeva
che l'acqua fosse addosso all'esagono cliccato, e dava errore a chi aveva puntato il fiume un dito
più in là — o a chi aveva puntato un fiume che corre sul **bordo**, e quindi non sta dentro nessuno
dei due esagoni che si vedono. Dove si arriva davvero lo dice la rotta, non l'esagono cliccato: il
riquadro scrive quello.

Sotto, la rotta non è una passeggiata sui vertici: due esagoni attaccati lungo un fiume **si
dividono i vertici**, quindi cercare «il punto d'acqua più vicino all'arrivo» darebbe un cammino
lungo zero. Quello che si cerca è il momento in cui la barca *entra* nell'esagono d'arrivo, e
quindi lo stato del viaggio è la coppia «dove sono sull'acqua, in che esagono sono». Fra due
strade sull'acqua esce quella che costa meno davvero, non quella disegnata con meno pezzi.

#### Nuotare

Sulla scheda di un personaggio c'è la **Velocità di Nuotare**, zero per chi non ne ha una. La wiki
la mette accanto al veicolo come secondo modo di passare l'acqua, e qui fa esattamente quello: chi
nuota attraversa un Confine d'Acqua ed entra in un esagono d'acqua senza barca.

Vale però la regola di sempre — il gruppo va insieme e va come il suo membro più lento: se uno solo
non nuota, restano tutti sulla riva, e l'app dice **chi**. Il viaggio lungo il fiume resta roba da
barche: un nuotatore attraversa, non fa la rotta.

**Nuotare non è navigare.** Una barca sta *sull'*acqua: per lei le sponde di un esagono non
esistono, il fiume è la strada. Chi nuota cammina sulla terra come tutti e attraversa dove gli
serve, quindi le sponde restano: il suo segnalino sta su una sponda, la freccia parte da quella
sponda, e trascinando il righello si indica una sponda come per chiunque altro. Passare da una
all'altra non costa attività in più — la wiki non prezza la traversata a nuoto di un fiume dentro un
esagono, e metterci un numero sarebbe inventarlo — e nel dettaglio del piano quell'esagono porta
🏊 invece di 🌉. Dove il fiume c'è ma non si attraversa, i conti sono quelli di sempre.

#### La carta delle acque: portarla via e riportarla

Tracciare lo Shrike esagono per esagono è lavoro di mezz'ora, e finora quel lavoro viveva in un solo
database su un solo computer. **Scarica la carta** lo mette in un file: confini, rive e
attraversamenti insieme, in JSON. Si tiene come copia di sicurezza, e si manda a un altro tavolo che
gioca sulla stessa mappa.

Le quattro cose viaggiano insieme perché separate non vogliono dire niente: un ponte senza il fiume
che scavalca non attraversa nulla, una riva senza i suoi confini racconta metà corso d'acqua, e un
verso senza il tratto a cui si riferisce non dice da che parte scorra un bel niente. Nel file ci
sono infatti anche **i versi della corrente**, e all'apertura si tengono solo quelli che cadono su
un tratto che la carta stessa porta.

**Dentro c'è anche la taratura della griglia**, e non è un di più. Un confine è una coppia di
coordinate, e le coordinate vogliono dire qualcosa solo rispetto a una griglia: chi apre il file su
una mappa tarata diversamente deve saperlo *prima* di ritrovarsi i fiumi spostati di un esagono, e
l'unico modo perché lo sappia è che il file glielo dica. All'apertura l'app confronta e parla:

* **orientamento diverso** → si rifiuta. Lì le direzioni dei lati vorrebbero dire un'altra cosa, e
  applicarle sarebbe disegnare fiumi a caso;
* **griglia più piccola** → quello che cade fuori si perde, e ti dice quanto;
* **un'altra immagine, o la stessa tarata diversamente** → avviso, non blocco. Gli esagoni sono
  quelli, ma controlla che i fiumi cadano dove devono.

Quello che nel file è storto — un tipo che non esiste, coordinate che non sono numeri, rive che non
dividono davvero i sei lati — **si scarta e si conta**, senza far fallire il resto. Un file arriva da
fuori, e da fuori può arrivare qualunque cosa.

Come per la lettura dell'immagine, **caricare non applica**: la carta compare in arancione sulla
mappa, sopra quello che c'è già, e solo dopo scegli. *Sostituisci tutto* fa piazza pulita e mette la
carta al suo posto; *Aggiungi* tiene quello che c'è e ci mette sopra la carta. La scrittura è una
transazione sola: o entra tutta o non entra niente.

JSON e non un formato nostro: si apre con un editor, si legge, si corregge a mano se serve, e fra
dieci anni si legge ancora. È la stessa scelta dell'esportazione del regno. Il file si chiama
`acque-<regno>-<data>.json`, perché una cartella di copie con dentro tre `acque.json` non serve a
niente.

#### Leggere l'acqua dall'immagine

Nel riquadro *Acque*, **Leggi la mappa** guarda l'immagine di sfondo e **propone** quali lati sono
attraversati da acqua. Propone e basta — finché non premi *Accetta* non viene scritto niente, come
per le attività del turno.

Prima devi dirgli di che colore è l'acqua *su questa mappa*: `Prendi il colore dell'acqua`, e
clicchi due o tre punti sull'azzurro del disegno. Non lo indovina da solo, e c'è
un motivo preciso: un esagono segnato «Lago» dice dov'è il lago **nel gioco**, non che il centro
dell'esagono sia dipinto di blu. Sulla mappa delle Terre Rubate quei centri sono marroni come la
pianura, e dedurne il colore dava un riferimento indistinguibile dalla terra — cioè una lettura
senza senso ma dall'aria sicura. Se i punti che indichi non separano l'acqua dalla terra, l'app
si rifiuta di leggere e lo dice.

Come funziona: la lettura fa **due domande diverse**, perché un fiume può fare due cose diverse.

* *L'acqua scorre lungo questo confine?* — si campiona il lato stesso; se ne è bagnato almeno un
  quarto, il confine è acqua.
* *L'acqua taglia questo esagono?* — si prendono i punti di mezzo dei suoi sei lati e per ogni
  coppia si guarda se la corda che li unisce attraversa acqua. Quelli che si raggiungono senza
  bagnarsi stanno sulla stessa riva.

All'inizio la prima domanda era posta male — si guardava se c'era acqua *sulla linea fra i due
centri* — e su una mappa vera quella domanda ha quasi sempre risposta sì, perché quasi ogni fiume
attraversa qualcosa. Il risultato era murare interi esagoni asciutti: sulle Terre Rubate ne
restavano sei irraggiungibili, due dei quali senza una goccia d'acqua dentro.

L'immagine si guarda a **metà risoluzione**. A un quarto i ruscelli delle Terre Rubate sono righe
larghe uno o due pixel — al limite di quello che si distingue da un artefatto di compressione, e se
ne perdeva un terzo. A metà si vedono tutti e la lettura passa da due secondi a sette, che per una
cosa che si fa una volta per mappa non si sente.

**La proposta si vede sulla mappa** prima di accettarla, ed è tutto il punto: i lati proposti si
disegnano **in arancione**, sopra ogni altra cosa (i laghi non si leggono dall'immagine: si
disegnano col pennello Lago). Premi *Accetta* e diventano azzurri come gli altri; premi *Scarta* e spariscono
senza aver toccato niente. Serve perché sbaglia poco per eccesso e qualcosa per difetto, e ha un
punto debole noto: le **cime innevate** sono chiare e azzurrine come l'acqua, e ogni tanto
finiscono nell'elenco. I lati che cadono **fuori
dall'immagine** (l'immagine può coprire meno griglia di quanta ne è impostata) non vengono letti
e l'app li conta a parte: non sono terra, sono non letti. Una nuova lettura sostituisce solo
quello che aveva trovato lei: i confini segnati a mano restano dove li hai messi.

Serve **Pillow**, che non è installata di suo: `pip install "Pillow>=10,<12"`. Senza, il
pulsante te lo dice e non fa altro; tutto il resto funziona identico e i confini si segnano a
mano.

Un giocatore può pianificare solo attraverso esagoni che conosce: un percorso che attraversa la
nebbia sarebbe una notizia sul territorio che non ha ancora esplorato. Il GM vede i costi veri.

**La mappa finisce dove finisce l'immagine.** La griglia è 30×24, ma l'immagine copre meno righe e
sotto c'è il buio: prima un viaggio poteva andarci a passeggio — tracciato, prezzato e partito verso
un posto che non si vede. Un esagono è della mappa se il suo **centro cade sull'immagine**, la
stessa regola con cui è di un lago; vale per la griglia disegnata, per il clic e per ogni conto di
viaggio, e senza le misure dell'immagine resta la griglia.

**Viaggi in corso.** Le rotte già partite restano disegnate sulla mappa in ambra tratteggiata,
con un cerchietto sulla meta, e si accorciano da sole man mano che il gruppo cammina. **Sono la
stessa strada della proposta**: partono dal tondo di chi cammina, passano per le sponde e gli atomi
che la strada aveva toccato e finiscono nel pezzo puntato — la tratta li congela alla partenza
(nodi, atomi, posto d'arrivo), quindi la rotta non cambia se il GM ridisegna l'acqua domani, e chi fa
passare i giorni ferma la gente dove il piano diceva: i rami di un ritrovo sulla sponda del ritrovo,
la strada comune nel pezzo puntato. Si vedono
anche fuori dalla modalità Viaggio, perché dimenticarsi dove sta andando metà compagnia è
facile. **Cliccando l'icona** del pulsante *Viaggio* — solo l'icona, non il resto del pulsante —
le rotte si nascondono e l'icona si sbarra; ricliccandola tornano.

Più viaggi possono essere in corso insieme: chi parte è chi era selezionato in quel momento, e
quel gruppo viaggia come un gruppo.

**Partire sparsi.** Se chi parte non è tutto sullo stesso esagono compare la casella
**Viaggiate insieme**, accesa di suo. Accesa, il viaggio si fa in due tempi: prima ognuno
raggiunge un punto di ritrovo *alla propria Velocità*, poi da lì si prosegue insieme al passo
del più lento — la regola della wiki applicata solo alla parte che si fa davvero insieme.

Il punto di ritrovo lo sceglie l'app risolvendo, per ogni esagono possibile, il conto

    quando ci siamo tutti  =  max(tempo di ciascuno fino al ritrovo)
    quando siamo arrivati  =  quando ci siamo tutti + tempo dal ritrovo alla meta,
                              al passo del più lento

e prendendo l'esagono che fa **arrivare prima**; a parità di arrivo, quello dove **ci si ritrova
prima**. Non è un'euristica: con qualche centinaio di esagoni e quattro viaggiatori bastano
pochi Dijkstra e si prova ogni esagono, quindi il risultato è l'ottimo esatto.

L'ordine dei due criteri non è un dettaglio: garantisce che **ritrovarsi sia sempre gratis**.
Nessuno arriva più tardi di quanto arriverebbe partendo da solo — chi è veloce si limita a
passare il tempo di attesa camminando verso gli altri invece che fermo alla meta. Se qualcuno
sta rallentando il gruppo il riquadro lo dice in chiaro («da solo sarebbe a destinazione in 3
giorni invece di 10»): decidere se aspettarlo tocca al tavolo, non all'algoritmo.

Spegnendo **Viaggiate insieme** non si aspetta nessuno: parte un viaggio per ciascuno, ognuno
alla propria Velocità per la propria strada. È anche il modo di dividere la compagnia.

E si vede prima di partire. Con l'interruttore spento la mappa non disegna più una freccia sola:
ne disegna **una per viaggiatore**, ognuna del colore del suo personaggio e con la sua targhetta
— *«Argyon · 8 giorni»*, *«Galbanino · 12 giorni»* — impilate sopra la meta perché le strade
finiscono tutte lì. Vale trascinando e col tasto destro. Un solo gesto, e poi un solo **Parti**,
per creare tutte le partenze separate: prima bisognava rifare la stessa manovra una volta per
ciascuno.

**Anche qui la mano guida**, e guida tutte le frecce insieme. Alla pressione ognuno prende la
sua via più corta fin lì; da quel momento ogni passo del mouse si applica a tutte le strade, come
se si tenessero k righelli in parallelo — si allungano se l'esagono è nuovo, si accorciano se ci
erano già passate, e finiscono comunque tutte sotto il mouse, perché la meta resta una sola per
tutti. Quello che parte quando premi **Parti** è esattamente quello che stavi guardando: le
strade disegnate arrivano al server tutte quante, che le ricontrolla una per una e ricalcola solo
quelle che non stanno in piedi.

Sotto ai riquadri compare l'elenco di chi arriva quando: i numeri grandi in cima parlano del più
lento, che è il giorno in cui la compagnia è di nuovo tutta insieme a destinazione.

**Chi è già in viaggio.** Se fra i personaggi scelti c'è qualcuno che sta già andando da
qualche parte, il riquadro lo dice e non lascia partire finché non si decide: o si **annulla il
suo viaggio**, o lo si **toglie dal gruppo**. Metterlo in due viaggi insieme vorrebbe dire due
percorsi che ogni giorno lo spostano in due posti diversi.

**Vedere le strade che si uniscono.** Con più viaggiatori sparsi la freccia non è una sola: si
vedono i rami di avvicinamento di ognuno, il cerchietto del ritrovo dove si incontrano, e da lì
la strada comune fino alla meta, con i giorni totali. Vale con tutti e due i gesti — trascinando
o col tasto destro — e resta disegnata anche dopo aver scelto la meta. L'etichetta di un viaggio
di gruppo dice solo i giorni: le attività sono diverse per ognuno, e sommarle non vorrebbe dire
niente.

Il conto lo rifà il browser con la stessa formula del server, quindi l'anteprima mentre trascini
e il piano che compare dopo non possono dire due cose diverse.

Anche qui **la mano guida**, e guida la strada comune: quando premi, il ritrovo e i rami di
avvicinamento se li sceglie l'algoritmo, e da quel momento restano fermi; quello che continui a
disegnare trascinando è la strada che il gruppo fa unito, esagono per esagono, esattamente come
con un viaggiatore solo. Il ritrovo sta fermo apposta: con un mouse solo non si guidano tre
cammini insieme, e un punto d'incontro che si sposta da sé farebbe ballare la strada sotto le
dita mentre la stai tirando. Se il ritrovo non ti va bene, lascia il tasto e ricomincia da un
altro esagono. Tornando indietro fino al cerchietto la strada comune sparisce e resta solo il
raduno. Anche questa strada il server la ricontrolla, e se non regge — un salto, un terreno
impraticabile, qualcuno che al ritrovo non ci arriva — lo dice e rifà quella più economica.

**L'elenco dei viaggi.** Sotto il pianificatore c'è la lista dei viaggi in corso, ognuno nella
sua sezione apribile, con chi lo sta facendo, quanti giorni mancano e a che punto è ogni tratta.
Sceglierne uno — dal pulsante *Mostra sulla mappa*, cliccando la sua rotta sulla mappa, o
selezionando uno dei suoi viaggiatori — lo porta in cima all'elenco e lo accende sulla mappa,
così con quattro rotte in giro si sa di quale si sta parlando.

Il piano è una **proposta**, come le attività del turno: si guarda, si discute, e solo dopo
qualcuno preme il pulsante. I viaggi in cammino restano elencati anche nella scheda **Turno di
Regno**, dove si possono risolvere a mano senza aspettare che il tempo passi. Muovere i
segnalini lo può fare il GM, o un giocatore in un gruppo dove c'è un suo personaggio; chi l'ha
fatto resta scritto nel registro.

### Regia (solo Game Master)
Sopra la mappa, l'interruttore **«Vedi come i giocatori»** mostra la mappa esattamente come la
ricevono loro, senza cambiare account. La **nebbia** copre gli esagoni dove il gruppo non è mai stato: dalla tua parte resta leggera,
così leggi comunque la mappa e vedi a colpo d'occhio cosa i giocatori non hanno ancora, e li
vedi anche a griglia nascosta. Dalla loro parte è fitta, e il cursore accanto ai pulsanti ne
regola la densità **solo per loro**: da appena accennata, se i PG hanno un'idea di cosa
li aspetta, fino a coprire del tutto lo sfondo se le Terre Rubate sono un foglio bianco.

Rivelare un esagono non lo rende Ricognito: toglie la nebbia, cioè dice che il gruppo ne sa
qualcosa. Lo stato resta Sconosciuto finché non fanno davvero la Ricognizione.

Sopra la mappa c'è la barra **Nebbia**: *Copri* e *Scopri* cambiano il puntatore in un occhio
(sbarrato per coprire) e da lì clicchi direttamente gli esagoni. Un clic singolo apre subito la
finestra che chiede a chi applicarlo — tutto il gruppo o solo alcuni giocatori. Tenendo premuto
**ctrl** invece li accumuli, evidenziati in oro, e la finestra compare quando lasci il tasto;
se preferisci c'è anche il pulsante *Conferma*. *Reimposta* rimette la nebbia su tutti gli
esagoni ancora «Sconosciuto» — tutti quelli della griglia, non solo quelli su cui qualcuno ha
già cliccato.

Un esagono su cui nessuno ha ancora scritto niente non è «inesistente»: è solo vuoto. Nebbia e
conteggi ragionano sulla griglia intera, così i numeri tornano sempre (Sconosciuti + esplorati =
colonne × righe) e puoi coprire o scoprire qualsiasi esagono anche se non l'hai mai aperto.
Finché tieni accesa *Copri* o *Scopri* la griglia si vede tutta, per poterla cliccare. Il numero
di esagoni è limitato a 4000 in tutto: oltre, la mappa comincerebbe a scattare.

Il riquadro **Regia** accanto ai dettagli dell'esagono scelto contiene: rivela o nascondi al
gruppo, rivela a un solo giocatore, le tue note private e gli **elementi segreti**. Un elemento
segreto resta invisibile anche se l'esagono è già noto: lo riveli quando il gruppo lo scopre
davvero. Con l'occhio sbarrato puoi anche rendere di nuovo segreto un elemento già visibile,
senza doverlo cancellare e rifare.

Lo stesso vale per **strade, fortificazioni, terreni agricoli e siti di lavoro**: non sono
«elementi» ma caselle dell'esagono, e possono benissimo essere lì da prima che il regno
esistesse. Si creano con le loro caselle e si tengono
per sé con la spunta *segreto* che compare nel riquadro Regia appena la casella è attiva. Un
modo solo per ciascuna cosa: per questo non compaiono né nel menu *Aggiungi elemento* né fra gli
elementi segreti, dove erano un doppione della casella e mostravano l'icona sbagliata. I
salvataggi vecchi si convertono da soli al primo avvio. Sulla tua mappa un
segreto non raddoppia l'icona: è la stessa, con un 🔒 nell'angolo in basso a sinistra — come il
×2 dell'esagono Risorsa sta a destra. Così basta guardarla per sapere se il gruppo la vede.

La scheda **Regia** raccoglie il quadro d'insieme: quanti esagoni hai preparato, quanti sono
rivelati, la coda di quelli pronti, e i comandi che valgono per tutta la mappa.

### Regno
La scheda completa: caratteristiche e Rovine (punti / soglia / penalità), le 16 Abilità di
Regno con il modificatore calcolato e il tiro con un click, Ruoli di Governo assegnati ai
personaggi e con la Penalità di Assenza, Talenti di Regno, Prodotti con i limiti di magazzino, PR e Dadi Risorsa, Consumo.
Ogni tiro mostra il d20, la scomposizione del modificatore e il grado di successo.

### Turno di Regno
Le quattro fasi (Gestione, Commercio, Attività, Eventi) con i loro passi e le attività
disponibili in ciascuno. Pulsanti dedicati per i passi automatici: tirare i Dadi Risorsa,
raccogliere dai Siti di Lavoro, pagare il Consumo, controllare gli eventi casuali, convertire
i PR in PE, salire di livello. Ogni attività apre una scheda con requisiti, costo, descrizione,
scelta dell'abilità, CD e i quattro esiti; dopo il tiro compare l'esito esatto da applicare con
le regolazioni rapide a fianco (Malcontento, PR, PE, Fama, Rovine, Prodotti).
In cima alla scheda compaiono i **viaggi in corso** messi in coda dalla mappa: si risolvono da lì, quando il gruppo arriva.

Il pulsante *Nuovo turno* sa solo andare avanti. Se lo hai premuto una volta di troppo, o stai
provando qualcosa e vuoi tornare indietro, il numero si corregge dalla matita ✏ lì accanto,
oppure dalla riga **Turno di Regno** in cima alle *Regolazioni rapide*: −/+ per un passo,
oppure clicca il numero e scrivilo. È una correzione di contabilità e nient'altro: non annulla
quello che è successo, non tocca PR, Fama o attività tentate, e non sposta la data della
campagna (per quella c'è 📅 nell'orologio). Se tornando indietro un modificatore temporaneo
torna valido, l'app te lo dice.

### Città
Griglia Urbana in stile city-builder: 9 isolati da 4 lotti, con gli isolati bloccati finché
l'insediamento non cresce. Cliccando un lotto si apre il catalogo delle 76 strutture filtrate
per livello del regno e lotti contigui disponibili, con costo, prova di costruzione, Bonus di
Oggetto ed Effetti. «Costruisci» paga il costo e tira la prova; «Piazza senza prova» serve per
le strutture preesistenti (per esempio quelle già presenti nel forte del Signore Cervo).
Sono gestiti anche Sovrappopolamento, Macerie, confini della griglia ed espansione
Villaggio → Paese → Città → Metropoli con i relativi requisiti.

### Manuale
Consultazione rapida: tabella delle 76 strutture, tutte le attività con i quattro esiti,
i Talenti di Regno, e le tabelle di Dimensione, Tipi di Insediamento, Livelli, Ricompense
Miliari, costi del Terreno Sconnesso ed Elementi del Terreno. Da qui si esporta il
salvataggio o si ricomincia da capo. Con la 1.0.0 i testi delle regole seguono la lingua
dell'interfaccia: in inglese vengono da Archives of Nethys.
