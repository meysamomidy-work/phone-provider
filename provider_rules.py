"""Detection rules for dealer website platforms (one ProviderRule per platform)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderRule:
    """One detectable platform."""

    provider_id: str
    display_name: str
    html_substrings: tuple[str, ...] = ()
    html_regexes: tuple[str, ...] = ()
    host_regexes: tuple[str, ...] = ()
    points_substring: int = 30
    points_regex: int = 25
    points_host: int = 35
    min_score: int = 25


PROVIDERS: list[ProviderRule] = [
    ProviderRule(
        provider_id='dealersync',
        display_name='DealerSync',
        html_substrings=(
            'dealersync.com',
            'cdn.dealersync.com',
            'powered by dealersync',
        ),
        html_regexes=(
            'dealersync\\.com',
            'cdn\\.dealersync\\.com',
            'dealersync\\.net',
        ),
        host_regexes=(
            '^.*\\.dealersync\\.com$',
            '^dealersync\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='dealr_cloud',
        display_name='Dealr.cloud',
        html_substrings=(
            'dealr.cloud',
            'powered by dealr',
            'dealrcloud',
        ),
        html_regexes=(
            'dealr\\.cloud',
            'cdn\\.dealr\\.cloud',
            'app\\.dealr\\.cloud',
        ),
        host_regexes=(
            '^.*\\.dealr\\.cloud$',
        ),
    ),
    ProviderRule(
        provider_id='dealercenter',
        display_name='DealerCenter',
        html_substrings=(
            'lib.dealercenterwsstatic.net',
            'imagescf.dealercenter.net',
            'dcdws.blob.core.windows.net',
            'dwssecuredforms.dealercenter.net',
            '/dealercenter/img/',
            'dealercenter.website',
            'dws-website-by',
        ),
        html_regexes=(
            'lib\\.dealercenterwsstatic\\.net',
            'imagescf\\.dealercenter\\.net',
            'dcdws\\.blob\\.core\\.windows\\.net/dws-\\d+',
            'dwssecuredforms\\.dealercenter\\.net',
            'chat-cf\\.dealercenter\\.net',
            '/dealercenter/(?:img|fonts|lib)/',
            'var\\s+dws_const_',
            'id=[\'\\"]dws_[^\'\\"]+[\'\\"]',
            '#dwsmainwrapper',
            'data-handle=[\'\\"]dws_',
        ),
        host_regexes=(
            '^lib\\.dealercenterwsstatic\\.net$',
            '^imagescf\\.dealercenter\\.net$',
            '^chat-cf\\.dealercenter\\.net$',
            '^dwssecuredforms\\.dealercenter\\.net$',
        ),
        points_substring=35, points_regex=28, points_host=40,
    ),
    ProviderRule(
        provider_id='carsforsale',
        display_name='CarsForSale',
        html_substrings=(
            'powered by carsforsale.com',
            'powered by carsforsale',
            'siteflex',
        ),
        html_regexes=(
            'cdn\\d{2}\\.carsforsale\\.com',
            'signin\\.carsforsale\\.com',
            'carsforsale\\.com/wwwroot/bundles/',
            'carsforsale\\.com/dealerlogos/',
            'dns-prefetch[^>]+cdn\\d{2}\\.carsforsale\\.com',
        ),
        host_regexes=(
            '^cdn\\d{2}\\.carsforsale\\.com$',
            '^signin\\.carsforsale\\.com$',
            '^images\\.carsforsale\\.com$',
        ),
        points_substring=40, points_regex=30, points_host=40,
    ),
    ProviderRule(
        provider_id='dealer_car_search',
        display_name='Dealer Car Search',
        html_substrings=(
            'dealercarsearch.com',
            'dealer car search',
            'dcsinventory',
        ),
        html_regexes=(
            'dealercarsearch\\.com',
            'cdn\\.dealercarsearch\\.com',
            'dcsinventory',
        ),
        host_regexes=(
            '^.*\\.dealercarsearch\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='automanager',
        display_name='AutoManager',
        html_substrings=(
            'automanager.com',
            'powered by automanager',
            'zoocar.com',
            'deskmanager',
        ),
        html_regexes=(
            'automanager\\.com',
            'cdn\\.automanager\\.com',
            'zoocar\\.com',
            'deskmanageronline',
        ),
        host_regexes=(
            '^.*\\.automanager\\.com$',
            '^.*\\.zoocar\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='frazer',
        display_name='Frazer DMS',
        html_substrings=(
            'frazer.com',
            'frazer computing',
            'frazerdms',
        ),
        html_regexes=(
            'frazer\\.com',
            'frazercomputing\\.com',
            'frazerdms',
        ),
        host_regexes=(
            '^.*\\.frazer\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='dealer_essential',
        display_name='Dealer Essential',
        html_substrings=(
            'dealeressential.com',
            'dealer essential',
            'powered by dealer essential',
        ),
        html_regexes=(
            'dealeressential\\.com',
            'cdn\\.dealeressential\\.com',
            'app\\.dealeressential\\.com',
        ),
        host_regexes=(
            '^.*\\.dealeressential\\.com$',
            '^dealeressential\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='foxdms',
        display_name='FoxDMS',
        html_substrings=(
            'foxdms.com',
            'fox dms',
            'powered by foxdms',
        ),
        html_regexes=(
            'foxdms\\.com',
            'cdn\\.foxdms\\.com',
            'app\\.foxdms\\.com',
        ),
        host_regexes=(
            '^.*\\.foxdms\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='jouver',
        display_name='Jouver',
        html_substrings=(
            'jouver.com',
            'jouver.io',
            'powered by jouver',
        ),
        html_regexes=(
            'jouver\\.com',
            'jouver\\.io',
            'cdn\\.jouver\\.io',
        ),
        host_regexes=(
            '^.*\\.jouver\\.com$',
            '^.*\\.jouver\\.io$',
        ),
    ),
    ProviderRule(
        provider_id='autosoft',
        display_name='Autosoft',
        html_substrings=(
            'autosoftdms.com',
            'autosoft.com',
            'autosoft dms',
        ),
        html_regexes=(
            'autosoftdms\\.com',
            'autosoft\\.com',
            'cdn\\.autosoftdms\\.com',
        ),
        host_regexes=(
            '^.*\\.autosoftdms\\.com$',
            '^.*\\.autosoft\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='carbase',
        display_name='Carbase',
        html_substrings=(
            'carbase.com',
            'powered by carbase',
            'carbase dealer',
        ),
        html_regexes=(
            'carbase\\.com',
            'cdn\\.carbase\\.com',
            'app\\.carbase\\.com',
        ),
        host_regexes=(
            '^.*\\.carbase\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='aax',
        display_name='AAX',
        html_substrings=(
            'aaxsys.com',
            'aax.com',
            'aax dynamic',
        ),
        html_regexes=(
            'aaxsys\\.com',
            'aax\\.com',
            'cdn\\.aaxsys\\.com',
        ),
        host_regexes=(
            '^.*\\.aaxsys\\.com$',
            '^.*\\.aax\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='autostar_solutions',
        display_name='AutoStar Solutions',
        html_substrings=(
            'autostarsolutions.com',
            'autostar solutions',
            'autostar dms',
        ),
        html_regexes=(
            'autostarsolutions\\.com',
            'cdn\\.autostarsolutions\\.com',
        ),
        host_regexes=(
            '^.*\\.autostarsolutions\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='prime_dms',
        display_name='Prime DMS',
        html_substrings=(
            'primedms.com',
            'prime dms',
            'powered by prime',
        ),
        html_regexes=(
            'primedms\\.com',
            'cdn\\.primedms\\.com',
        ),
        host_regexes=(
            '^.*\\.primedms\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='wayne_reaves',
        display_name='Wayne Reaves',
        html_substrings=(
            'waynereaves.com',
            'wayne reaves',
            'wayne reaves dealer',
        ),
        html_regexes=(
            'waynereaves\\.com',
            'cdn\\.waynereaves\\.com',
        ),
        host_regexes=(
            '^.*\\.waynereaves\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='dominion_dms',
        display_name='Dominion DMS',
        html_substrings=(
            'dominiondms.com',
            'dominion dms',
            'dominion dealer solutions',
        ),
        html_regexes=(
            'dominiondms\\.com',
            'cdn\\.dominiondms\\.com',
        ),
        host_regexes=(
            '^.*\\.dominiondms\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='lotwizard',
        display_name='LotWizard',
        html_substrings=(
            'lotwizard.com',
            'lot wizard',
            'powered by lotwizard',
        ),
        html_regexes=(
            'lotwizard\\.com',
            'cdn\\.lotwizard\\.com',
        ),
        host_regexes=(
            '^.*\\.lotwizard\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='dealer_com',
        display_name='Dealer.com',
        html_substrings=(
            'dealer.com',
            'dealer.com websites',
            'cdn.dealer.com',
            'powered by dealer.com',
        ),
        html_regexes=(
            'dealer\\.com',
            'cdn\\.dealer\\.com',
            'static\\.dealer\\.com',
            'websites\\.dealer\\.com',
        ),
        host_regexes=(
            '^.*\\.dealer\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='dealerfx',
        display_name='DealerFX',
        html_substrings=(
            'dealerfx.com',
            'dealer fx',
            'dealerfx scheduling',
        ),
        html_regexes=(
            'dealerfx\\.com',
            'cdn\\.dealerfx\\.com',
            'app\\.dealerfx\\.com',
        ),
        host_regexes=(
            '^.*\\.dealerfx\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='cox_automotive',
        display_name='Cox Automotive',
        html_substrings=(
            'coxautoinc.com',
            'coxautomotive.com',
            'cox automotive',
        ),
        html_regexes=(
            'coxautoinc\\.com',
            'coxautomotive\\.com',
            'cdn\\.coxautoinc\\.com',
        ),
        host_regexes=(
            '^.*\\.coxautoinc\\.com$',
            '^.*\\.coxautomotive\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='xtime',
        display_name='Xtime',
        html_substrings=(
            'xtime.com',
            'xtime scheduling',
            'powered by xtime',
        ),
        html_regexes=(
            'xtime\\.com',
            'cdn\\.xtime\\.com',
            'consumer\\.xtime\\.com',
        ),
        host_regexes=(
            '^.*\\.xtime\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='autoweb',
        display_name='AutoWeb',
        html_substrings=(
            'autoweb.com',
            'dealerweb.com',
            'autoweb dealer',
        ),
        html_regexes=(
            'autoweb\\.com',
            'dealerweb\\.com',
            'cdn\\.autoweb\\.com',
        ),
        host_regexes=(
            '^.*\\.autoweb\\.com$',
            '^.*\\.dealerweb\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='motosnap',
        display_name='MotoSnap',
        html_substrings=(
            'motosnap.com',
            'motosnap dealer',
            'powered by motosnap',
        ),
        html_regexes=(
            'motosnap\\.com',
            'cdn\\.motosnap\\.com',
        ),
        host_regexes=(
            '^.*\\.motosnap\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='autorevo',
        display_name='AutoRevo',
        html_substrings=(
            'autorevo.com',
            'autorevo dealer',
            'powered by autorevo',
        ),
        html_regexes=(
            'autorevo\\.com',
            'cdn\\.autorevo\\.com',
        ),
        host_regexes=(
            '^.*\\.autorevo\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='gubagoo',
        display_name='Gubagoo',
        html_substrings=(
            'gubagoo.com',
            'gubagoo chat',
            'powered by gubagoo',
        ),
        html_regexes=(
            'gubagoo\\.com',
            'cdn\\.gubagoo\\.com',
            'widget\\.gubagoo\\.com',
        ),
        host_regexes=(
            '^.*\\.gubagoo\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='podium',
        display_name='Podium',
        html_substrings=(
            'podium.com',
            'podium chat',
            'podium reviews',
        ),
        html_regexes=(
            'podium\\.com',
            'cdn\\.podium\\.com',
            'widget\\.podium\\.com',
        ),
        host_regexes=(
            '^.*\\.podium\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='fullpath',
        display_name='Fullpath',
        html_substrings=(
            'fullpath.com',
            'autoleadstar.com',
            'fullpath automotive',
        ),
        html_regexes=(
            'fullpath\\.com',
            'autoleadstar\\.com',
            'cdn\\.fullpath\\.com',
        ),
        host_regexes=(
            '^.*\\.fullpath\\.com$',
            '^.*\\.autoleadstar\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='convertus',
        display_name='Convertus',
        html_substrings=(
            'convertus.com',
            'convertus vms',
            'powered by convertus',
        ),
        html_regexes=(
            'convertus\\.com',
            'cdn\\.convertus\\.com',
            'vms\\.convertus\\.com',
        ),
        host_regexes=(
            '^.*\\.convertus\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='foureyes',
        display_name='Foureyes',
        html_substrings=(
            'foureyes.io',
            'foureyes.com',
            'foureyes consent',
        ),
        html_regexes=(
            'foureyes\\.io',
            'foureyes\\.com',
            'cdn\\.foureyes\\.io',
        ),
        host_regexes=(
            '^.*\\.foureyes\\.io$',
            '^.*\\.foureyes\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='callrevu',
        display_name='CallRevu',
        html_substrings=(
            'callrevu.com',
            'call revu',
            'powered by callrevu',
        ),
        html_regexes=(
            'callrevu\\.com',
            'cdn\\.callrevu\\.com',
        ),
        host_regexes=(
            '^.*\\.callrevu\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='cdk',
        display_name='CDK Global',
        html_substrings=(
            'cdkglobal.com',
            'cdk.com',
            'digital dealers',
            'elead',
            'fortellis',
        ),
        html_regexes=(
            'cdkglobal\\.com',
            'cdk\\.com/(?:assets|scripts)',
            'eleadcrm\\.com',
            'fortellis\\.io',
            'digitaldealers',
        ),
        host_regexes=(
            '^.*\\.cdkglobal\\.com$',
            '^.*\\.eleadcrm\\.com$',
            '^.*\\.fortellis\\.io$',
        ),
    ),
    ProviderRule(
        provider_id='tekion',
        display_name='Tekion',
        html_substrings=(
            'tekion.com',
            'tekioncloud',
            'tekion api',
        ),
        html_regexes=(
            'tekion\\.com',
            'tekioncloud\\.com',
            'cdn\\.tekion\\.io',
            'api\\.tekion\\.io',
        ),
        host_regexes=(
            '^.*\\.tekion\\.com$',
            '^.*\\.tekioncloud\\.com$',
            '^.*\\.tekion\\.io$',
        ),
    ),
    ProviderRule(
        provider_id='vinsolutions',
        display_name='VinSolutions',
        html_substrings=(
            'vinsolutions.com',
            'vin solutions',
            'contactatonce',
            'leadbox',
            'caochathub',
        ),
        html_regexes=(
            'vinsolutions\\.com',
            'vinconnect\\.com',
            'contactatonce\\.com',
            'leadbox\\.com',
            'caochathub',
        ),
        host_regexes=(
            '^.*\\.vinsolutions\\.com$',
            '^.*\\.contactatonce\\.com$',
            '^.*\\.leadbox\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='dealersocket',
        display_name='DealerSocket',
        html_substrings=(
            'dealersocket.com',
            'dealer socket',
            'dsnextgen',
            'inventoryplus',
        ),
        html_regexes=(
            'dealersocket\\.com',
            'dsnextgen\\.com',
            'inventoryplus\\.dealersocket',
            'cdn\\.dealersocket\\.com',
        ),
        host_regexes=(
            '^.*\\.dealersocket\\.com$',
            '^.*\\.dsnextgen\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='reynolds_reynolds',
        display_name='Reynolds & Reynolds',
        html_substrings=(
            'reynoldsandreynolds.com',
            'reyrey.com',
            'reynolds and reynolds',
        ),
        html_regexes=(
            'reynoldsandreynolds\\.com',
            'reyrey\\.com',
            'cdn\\.reyrey\\.com',
        ),
        host_regexes=(
            '^.*\\.reynoldsandreynolds\\.com$',
            '^.*\\.reyrey\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='era_dms',
        display_name='ERA DMS',
        html_substrings=(
            'eradms.com',
            'era dms',
            'era-ignite',
        ),
        html_regexes=(
            'eradms\\.com',
            'era-dms\\.com',
            'cdn\\.eradms\\.com',
        ),
        host_regexes=(
            '^.*\\.eradms\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='ignite_dms',
        display_name='Ignite DMS',
        html_substrings=(
            'ignitedms.com',
            'ignite dms',
            'ignite dealer',
        ),
        html_regexes=(
            'ignitedms\\.com',
            'cdn\\.ignitedms\\.com',
        ),
        host_regexes=(
            '^.*\\.ignitedms\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='pbs_systems',
        display_name='PBS Systems',
        html_substrings=(
            'pbssystems.com',
            'pbs systems',
            'pbs dealer',
        ),
        html_regexes=(
            'pbssystems\\.com',
            'cdn\\.pbssystems\\.com',
        ),
        host_regexes=(
            '^.*\\.pbssystems\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='dealertrack_dms',
        display_name='Dealertrack DMS',
        html_substrings=(
            'dealertrack.com',
            'dealertrack dms',
            'cox dealertrack',
        ),
        html_regexes=(
            'dealertrack\\.com',
            'cdn\\.dealertrack\\.com',
            'dms\\.dealertrack\\.com',
        ),
        host_regexes=(
            '^.*\\.dealertrack\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='dealeron',
        display_name='DealerOn',
        html_substrings=(
            'dealeron.com',
            'static.dealeron.com',
            'powered by dealeron',
        ),
        html_regexes=(
            'dealeron\\.com',
            'static\\.dealeron\\.com',
            'assets\\.dealeron\\.com',
            'cdn\\.dealeron\\.com',
        ),
        host_regexes=(
            '^.*\\.dealeron\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='dealer_inspire',
        display_name='Dealer Inspire',
        html_substrings=(
            'dealerinspire.com',
            'dealer inspire',
            'di-uploads',
            'cdn.dealerinspire',
        ),
        html_regexes=(
            'dealerinspire\\.com',
            'cdn\\.dealerinspire\\.com',
            'di-uploads',
            'dealerinspire\\.net',
        ),
        host_regexes=(
            '^.*\\.dealerinspire\\.com$',
            '^.*\\.dealerinspire\\.net$',
        ),
    ),
    ProviderRule(
        provider_id='dealer_eprocess',
        display_name='Dealer eProcess',
        html_substrings=(
            'dealereprocess.com',
            'dealer eprocess',
            'powered by dealereprocess',
        ),
        html_regexes=(
            'dealereprocess\\.com',
            'cdn\\.dealereprocess\\.com',
        ),
        host_regexes=(
            '^.*\\.dealereprocess\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='jazel_auto',
        display_name='Jazel Auto',
        html_substrings=(
            'jazelauto.com',
            'jazel auto',
            'jazel inventory',
        ),
        html_regexes=(
            'jazelauto\\.com',
            'cdn\\.jazelauto\\.com',
        ),
        host_regexes=(
            '^.*\\.jazelauto\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='dealerfire',
        display_name='DealerFire',
        html_substrings=(
            'dealerfire.com',
            'dealer fire',
            'powered by dealerfire',
        ),
        html_regexes=(
            'dealerfire\\.com',
            'cdn\\.dealerfire\\.com',
        ),
        host_regexes=(
            '^.*\\.dealerfire\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='lotlinx',
        display_name='LotLinx',
        html_substrings=(
            'lotlinx.com',
            'lotlinx',
            'powered by lotlinx',
        ),
        html_regexes=(
            'lotlinx\\.com',
            'cdn\\.lotlinx\\.com',
        ),
        host_regexes=(
            '^.*\\.lotlinx\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='autojini',
        display_name='AutoJini',
        html_substrings=(
            'autojini.com',
            'autojini',
            'powered by autojini',
        ),
        html_regexes=(
            'autojini\\.com',
            'cdn\\.autojini\\.com',
        ),
        host_regexes=(
            '^.*\\.autojini\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='ebizautos',
        display_name='eBizAutos',
        html_substrings=(
            'ebizautos.com',
            'ebiz autos',
            'powered by ebizautos',
        ),
        html_regexes=(
            'ebizautos\\.com',
            'cdn\\.ebizautos\\.com',
        ),
        host_regexes=(
            '^.*\\.ebizautos\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='team_velocity',
        display_name='Team Velocity',
        html_substrings=(
            'teamvelocity.com',
            'teamvelocitymarketing.com',
            'team velocity',
        ),
        html_regexes=(
            'teamvelocity\\.com',
            'teamvelocitymarketing\\.com',
            'cdn\\.teamvelocity\\.com',
        ),
        host_regexes=(
            '^.*\\.teamvelocity\\.com$',
            '^.*\\.teamvelocitymarketing\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='autosweet',
        display_name='AutoSweet',
        html_substrings=(
            'autosweet.com',
            'autosweet',
            'powered by autosweet',
        ),
        html_regexes=(
            'autosweet\\.com',
            'cdn\\.autosweet\\.com',
        ),
        host_regexes=(
            '^.*\\.autosweet\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='overfuel',
        display_name='Overfuel',
        html_substrings=(
            'overfuel.com',
            'overfuel',
            'powered by overfuel',
        ),
        html_regexes=(
            'overfuel\\.com',
            'cdn\\.overfuel\\.com',
        ),
        host_regexes=(
            '^.*\\.overfuel\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='carnow',
        display_name='CarNow',
        html_substrings=(
            'gocarnow.com',
            'carnow.com',
            'carnow chat',
        ),
        html_regexes=(
            'gocarnow\\.com',
            'carnow\\.com',
            'cdn\\.gocarnow\\.com',
        ),
        host_regexes=(
            '^.*\\.gocarnow\\.com$',
            '^.*\\.carnow\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='cargurus_digital_deal',
        display_name='CarGurus Digital Deal',
        html_substrings=(
            'cargurus.com',
            'digitaldeal.cargurus.com',
            'cargurus digital deal',
        ),
        html_regexes=(
            'cargurus\\.com',
            'digitaldeal\\.cargurus\\.com',
            'cdn\\.cargurus\\.com',
        ),
        host_regexes=(
            '^.*\\.cargurus\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='autoleadstar',
        display_name='AutoLeadStar',
        html_substrings=(
            'autoleadstar.com',
            'autoleadstar',
            'powered by autoleadstar',
        ),
        html_regexes=(
            'autoleadstar\\.com',
            'cdn\\.autoleadstar\\.com',
        ),
        host_regexes=(
            '^.*\\.autoleadstar\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='autofi',
        display_name='AutoFi',
        html_substrings=(
            'autofi.com',
            'autofi',
            'autofi commerce',
        ),
        html_regexes=(
            'autofi\\.com',
            'cdn\\.autofi\\.com',
            'app\\.autofi\\.com',
        ),
        host_regexes=(
            '^.*\\.autofi\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='roadster',
        display_name='Roadster',
        html_substrings=(
            'roadster.com',
            'roadster express',
            'roadster dealer',
        ),
        html_regexes=(
            'roadster\\.com',
            'cdn\\.roadster\\.com',
            'app\\.roadster\\.com',
        ),
        host_regexes=(
            '^.*\\.roadster\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='elead_crm',
        display_name='Elead CRM',
        html_substrings=(
            'eleadcrm.com',
            'elead crm',
            'elead one',
        ),
        html_regexes=(
            'eleadcrm\\.com',
            'cdn\\.eleadcrm\\.com',
            'elead1\\.com',
        ),
        host_regexes=(
            '^.*\\.eleadcrm\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='promax',
        display_name='ProMax',
        html_substrings=(
            'promaxunlimited.com',
            'promax.com',
            'promax crm',
        ),
        html_regexes=(
            'promaxunlimited\\.com',
            'promax\\.com',
            'cdn\\.promaxunlimited\\.com',
        ),
        host_regexes=(
            '^.*\\.promaxunlimited\\.com$',
            '^.*\\.promax\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='drivecentric',
        display_name='DriveCentric',
        html_substrings=(
            'drivecentric.com',
            'drive centric',
            'powered by drivecentric',
        ),
        html_regexes=(
            'drivecentric\\.com',
            'cdn\\.drivecentric\\.com',
        ),
        host_regexes=(
            '^.*\\.drivecentric\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='autoraptor',
        display_name='AutoRaptor',
        html_substrings=(
            'autoraptor.com',
            'autoraptor',
            'powered by autoraptor',
        ),
        html_regexes=(
            'autoraptor\\.com',
            'cdn\\.autoraptor\\.com',
        ),
        host_regexes=(
            '^.*\\.autoraptor\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='selly_automotive',
        display_name='Selly Automotive',
        html_substrings=(
            'sellyautomotive.com',
            'sellyserver.co',
            'selly automotive',
        ),
        html_regexes=(
            'sellyautomotive\\.com',
            'sellyserver\\.co',
            'cdn\\.sellyautomotive\\.com',
        ),
        host_regexes=(
            '^.*\\.sellyautomotive\\.com$',
            '^.*\\.sellyserver\\.co$',
        ),
    ),
    ProviderRule(
        provider_id='imagiclab_crm',
        display_name='iMagicLab CRM',
        html_substrings=(
            'imagiclab.com',
            'imagic lab',
            'imagiclab crm',
        ),
        html_regexes=(
            'imagiclab\\.com',
            'cdn\\.imagiclab\\.com',
        ),
        host_regexes=(
            '^.*\\.imagiclab\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='salesforce_automotive',
        display_name='Salesforce Automotive',
        html_substrings=(
            'salesforce.com/automotive',
            'automotive cloud',
            'force.com',
            'salesforce automotive',
        ),
        html_regexes=(
            'salesforce\\.com/.{0,40}automotive',
            'automotive\\.force\\.com',
            'cdn\\.salesforce\\.com',
        ),
        host_regexes=(
            '^.*\\.force\\.com$',
            '^.*\\.salesforce\\.com$',
        ),
        min_score=30,
    ),
    ProviderRule(
        provider_id='vincue',
        display_name='VinCue',
        html_substrings=(
            'vincue.com',
            'vincue crm',
            'powered by vincue',
        ),
        html_regexes=(
            'vincue\\.com',
            'cdn\\.vincue\\.com',
            'app\\.vincue\\.com',
        ),
        host_regexes=(
            '^.*\\.vincue\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='activix_crm',
        display_name='Activix CRM',
        html_substrings=(
            'activix.ca',
            'activix.com',
            'activix crm',
        ),
        html_regexes=(
            'activix\\.ca',
            'activix\\.com',
            'cdn\\.activix\\.ca',
        ),
        host_regexes=(
            '^.*\\.activix\\.ca$',
            '^.*\\.activix\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='homenet_automotive',
        display_name='HomeNet Automotive',
        html_substrings=(
            'homenetiol.com',
            'homenetautomotive.com',
            'homenet automotive',
        ),
        html_regexes=(
            'homenetiol\\.com',
            'homenetautomotive\\.com',
            'cdn\\.homenetiol\\.com',
        ),
        host_regexes=(
            '^.*\\.homenetiol\\.com$',
            '^.*\\.homenetautomotive\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='vauto',
        display_name='vAuto',
        html_substrings=(
            'vauto.com',
            'vauto provision',
            'powered by vauto',
        ),
        html_regexes=(
            'vauto\\.com',
            'cdn\\.vauto\\.com',
            'provision\\.vauto\\.com',
        ),
        host_regexes=(
            '^.*\\.vauto\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='inventory_plus',
        display_name='Inventory+',
        html_substrings=(
            'inventoryplus.com',
            'inventoryplus.dealersocket',
            'inventory plus',
        ),
        html_regexes=(
            'inventoryplus\\.com',
            'inventoryplus\\.dealersocket',
            'cdn\\.inventoryplus\\.com',
        ),
        host_regexes=(
            '^.*\\.inventoryplus\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='max_digital',
        display_name='MAX Digital',
        html_substrings=(
            'maxdigital.com',
            'max digital',
            'maxdigital showroom',
        ),
        html_regexes=(
            'maxdigital\\.com',
            'cdn\\.maxdigital\\.com',
        ),
        host_regexes=(
            '^.*\\.maxdigital\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='rapid_recon',
        display_name='Rapid Recon',
        html_substrings=(
            'rapidrecon.com',
            'rapid recon',
            'powered by rapidrecon',
        ),
        html_regexes=(
            'rapidrecon\\.com',
            'cdn\\.rapidrecon\\.com',
        ),
        host_regexes=(
            '^.*\\.rapidrecon\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='auction123',
        display_name='Auction123',
        html_substrings=(
            'auction123.com',
            'auction123',
            'powered by auction123',
        ),
        html_regexes=(
            'auction123\\.com',
            'cdn\\.auction123\\.com',
        ),
        host_regexes=(
            '^.*\\.auction123\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='car_merchant',
        display_name='Car-Merchant',
        html_substrings=(
            'car-merchant.com',
            'carmerchant.com',
            'car merchant',
        ),
        html_regexes=(
            'car-merchant\\.com',
            'carmerchant\\.com',
            'cdn\\.car-merchant\\.com',
        ),
        host_regexes=(
            '^.*\\.car-merchant\\.com$',
            '^.*\\.carmerchant\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='vincue_inventory',
        display_name='VINCue Inventory',
        html_substrings=(
            'vincue.com/inventory',
            'vincue inventory',
            'vincue merchandising',
        ),
        html_regexes=(
            'vincue\\.com/.{0,30}inventory',
            'inventory\\.vincue\\.com',
            'cdn\\.vincue\\.com',
        ),
        host_regexes=(
            '^inventory\\.vincue\\.com$',
            '^.*\\.vincue\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='lotvantage',
        display_name='LotVantage',
        html_substrings=(
            'lotvantage.com',
            'lot vantage',
            'powered by lotvantage',
        ),
        html_regexes=(
            'lotvantage\\.com',
            'cdn\\.lotvantage\\.com',
        ),
        host_regexes=(
            '^.*\\.lotvantage\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='auto_master_systems',
        display_name='Auto Master Systems',
        html_substrings=(
            'automastersystems.com',
            'auto master systems',
            'ams dealer',
        ),
        html_regexes=(
            'automastersystems\\.com',
            'cdn\\.automastersystems\\.com',
        ),
        host_regexes=(
            '^.*\\.automastersystems\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='nowcom',
        display_name='Nowcom',
        html_substrings=(
            'nowcom.com',
            'nowcom',
            'powered by nowcom',
        ),
        html_regexes=(
            'nowcom\\.com',
            'cdn\\.nowcom\\.com',
        ),
        host_regexes=(
            '^.*\\.nowcom\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='dealerclick',
        display_name='DealerClick',
        html_substrings=(
            'dealerclick.com',
            'dealer click',
            'powered by dealerclick',
        ),
        html_regexes=(
            'dealerclick\\.com',
            'cdn\\.dealerclick\\.com',
        ),
        host_regexes=(
            '^.*\\.dealerclick\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='autozoom',
        display_name='AutoZoom',
        html_substrings=(
            'autozoom.com',
            'autozoom',
            'powered by autozoom',
        ),
        html_regexes=(
            'autozoom\\.com',
            'cdn\\.autozoom\\.com',
        ),
        host_regexes=(
            '^.*\\.autozoom\\.com$',
        ),
    ),
    ProviderRule(
        provider_id='dpc_global',
        display_name='DPC Global',
        html_substrings=(
            'dpcglobal.com',
            'dpc global',
            'dpc software',
        ),
        html_regexes=(
            'dpcglobal\\.com',
            'cdn\\.dpcglobal\\.com',
        ),
        host_regexes=(
            '^.*\\.dpcglobal\\.com$',
        ),
    ),
]
