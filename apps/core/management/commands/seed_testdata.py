"""``seed_testdata``: fill the database with a coherent demo scenario.

    python manage.py seed_testdata             # demo ma'lumotni qo'shadi
    python manage.py seed_testdata --flush     # avvalgi demo qatorlarini o'chiradi
    python manage.py seed_testdata --scale 2   # yo'lovchilar sonini ikki barobarga oshiradi

Every row goes through the real service layer, so the demo data obeys the same
business rules as production data: a driver may only publish a trip while the
profile, the vehicle and the subscription are valid, seats are accounted for by
the same transitions, and no illegal state jump is faked. Nothing here contacts
the network: neither the 2GIS geocoder nor the payment provider is called.

``--flush`` removes only the rows whose owner starts with ``demo_``; the
geographical catalogue and the subscription plans are business data and are kept
(and reused, so seeding twice is harmless).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.chat import services as chat_services
from apps.chat.models import ChatMessage, ChatThread
from apps.locations import services as location_services
from apps.notifications.models import Notification
from apps.orders import services as order_services
from apps.orders.models import Order
from apps.payments import services as payment_services
from apps.payments.models import Payment
from apps.rides import services as ride_services
from apps.rides.models import DriverTrip, PassengerRequest
from apps.reviews import services as review_services
from apps.reviews.models import Review
from apps.subscriptions import services as subscription_services
from apps.subscriptions.models import DriverSubscription
from apps.subscriptions.selectors import get_plan_queryset
from apps.support import services as support_services
from apps.support.models import SupportMessage, SupportTicket
from apps.users import services as user_services
from apps.users.constants import UserRole
from apps.users.models import DriverProfile
from apps.vehicles import services as vehicle_services
from apps.vehicles.models import Vehicle

User = get_user_model()

#: Every demo account starts with this prefix; ``--flush`` finds its rows by it.
DEMO_PREFIX = "demo_"

ADMIN_USERNAME = f"{DEMO_PREFIX}support"
ADMIN_PASSWORD = "demo-support-123"

PLANS = (
    {
        "name": "1 oy",
        "duration_days": 30,
        "price": Decimal("30000.00"),
        "sort_order": 1,
        "description": "Bir oylik obuna.",
    },
    {
        "name": "3 oy",
        "duration_days": 90,
        "price": Decimal("80000.00"),
        "sort_order": 2,
        "description": "Uch oylik obuna, oyiga arzon.",
    },
    {
        "name": "6 oy",
        "duration_days": 180,
        "price": Decimal("150000.00"),
        "sort_order": 3,
        "description": "Yarim yillik obuna.",
    },
    {
        "name": "1 yil",
        "duration_days": 365,
        "price": Decimal("280000.00"),
        "sort_order": 4,
        "description": "Yillik obuna, eng arzon.",
    },
)

REGIONS = (
    {"name": "Toshkent shahri", "code": "TK"},
    {"name": "Toshkent viloyati", "code": "TO"},
    {"name": "Samarqand viloyati", "code": "SA"},
    {"name": "Jizzax viloyati", "code": "JI"},
    {"name": "Sirdaryo viloyati", "code": "SI"},
    {"name": "Qashqadaryo viloyati", "code": "QA"},
    {"name": "Surxondaryo viloyati", "code": "SU"},
    {"name": "Buxoro viloyati", "code": "BU"},
    {"name": "Navoiy viloyati", "code": "NA"},
    {"name": "Qoraqalpog'iston Respublikasi", "code": "QR"},
    {"name": "Xorazm viloyati", "code": "XO"},
    {"name": "Farg'ona viloyati", "code": "FA"},
    {"name": "Namangan viloyati", "code": "NM"},
    {"name": "Andijon viloyati", "code": "AN"},
)

DISTRICTS = (
    ("Toshkent shahri", "Sergeli tumani"),
    ("Toshkent shahri", "Yunusobod tumani"),
    ("Toshkent shahri", "Yuzeroy tumani"),
    ("Toshkent shahri", "Bektemir tumani"),
    ("Toshkent shahri", "Chilonzor tumani"),
    ("Toshkent viloyati", "Zangiota tumani"),
    ("Toshkent viloyati", "Chirchiq shahri"),
    ("Samarqand viloyati", "Samarqand shahri"),
    ("Samarqand viloyati", "Urgut tumani"),
    ("Jizzax viloyati", "Jizzax tumani"),
    ("Sirdaryo viloyati", "Guliston shahri"),
    ("Qashqadaryo viloyati", "Qarshi shahri"),
    ("Surxondaryo viloyati", "Termiz shahri"),
    ("Buxoro viloyati", "Buxoro shahri"),
    ("Navoiy viloyati", "Navoiy shahri"),
    ("Qoraqalpog'iston Respublikasi", "Nukus shahri"),
    ("Xorazm viloyati", "Urganch shahri"),
    ("Xorazm viloyati", "Xiva shahri"),
    ("Farg'ona viloyati", "Farg'ona shahri"),
    ("Namangan viloyati", "Namangan shahri"),
    ("Andijon viloyati", "Andijon shahri"),
)

#: Genuine Tashkent coordinates, so a seeded route is a real ride and not two
#: pins on the same street. Every route built from ROUTES is validated against
#: ``rides.constants.MIN_ROUTE_DISTANCE_KM`` before anything is written.
LOCATIONS = (
    ("sergeli", "Sergeli tumani", "Sergeli 8-maktab", "41.211000", "69.201000",
     "Sergeli tumani, Zarafshon ko'chasi, 12-uy"),
    ("yunusobod", "Yunusobod tumani", "Yunusobod markazi", "41.332000", "69.301000",
     "Yunusobod tumani, Sitora Mo'hiyeva ko'chasi"),
    ("yuzeroy", "Yuzeroy tumani", "Yuzeroy boshqaruvi", "41.279000", "69.142000",
     "Yuzeroy tumani, Zulfiya ko'chasi, 5"),
    ("bektemir", "Bektemir tumani", "Bektemir MFY", "41.223000", "69.162000",
     "Bektemir tumani, Og'aberdi ko'chasi, 88"),
    ("chilonzor", "Chilonzor tumani", "Chilonzor MFY", "41.290000", "69.228000",
     "Chilonzor tumani, Novoy ko'chasi, 41"),
    ("markaz", "Chilonzor tumani", "Mustaqillik maydoni", "41.299500", "69.240000",
     "Mustaqillik maydoni metro kirishi"),
    ("zangiota", "Zangiota tumani", "Zangiota markazi", "41.358000", "69.229000",
     "Zangiota tumani, Alisher Navoiy ko'chasi, 3"),
    ("chirchiq", "Chirchiq shahri", "Chirchiq shahri markazi", "41.440000", "69.487000",
     "Chirchiq shahri, Navoiy ko'chasi, 27"),
)

#: Regional centres the intercity rides start from Toshkent for. Intercity
#: routes are validated exactly like the intra-city ones, the distance between a
#: Tashkent district and any of these is far above ``MIN_ROUTE_DISTANCE_KM``.
REGION_LOCATIONS = (
    ("samarqand", "Samarqand shahri", "Samarqand Registon markazi", "39.626900", "66.960000",
     "Samarqand shahri, Registon ko'chasi"),
    ("urgut", "Urgut tumani", "Urgut markazi", "39.467000", "67.244000",
     "Urgut tumani, Al-Xorazmiy ko'chasi, 8"),
    ("jizzax", "Jizzax tumani", "Jizzax markazi", "40.115800", "67.842200",
     "Jizzax tumani, Samarqand ko'chasi, 15"),
    ("guliston", "Guliston shahri", "Guliston markazi", "40.342700", "67.590000",
     "Guliston shahri, Alisher Navoiy ko'chasi, 4"),
    ("qarshi", "Qarshi shahri", "Qarshi Chorvoh markazi", "41.550000", "67.150000",
     "Qarshi shahri, Chorvoh ko'chasi, 30"),
    ("termiz", "Termiz shahri", "Termiz markazi", "37.224200", "67.278300",
     "Termiz shahri, Alisher Navoiy ko'chasi, 6"),
    ("buxoro", "Buxoro shahri", "Buxoro Ark markazi", "39.768100", "64.455600",
     "Buxoro shahri, Ark ko'chasi, 2"),
    ("navoiy", "Navoiy shahri", "Navoiy markazi", "40.083300", "65.383300",
     "Navoiy shahri, Amir Timur ko'chasi, 21"),
    ("nukus", "Nukus shahri", "Nukus markazi", "42.453100", "59.610300",
     "Nukus shahri, Qongrad ko'chasi, 11"),
    ("urganch", "Urganch shahri", "Urganch Al-Xorazmiy markazi", "41.562500", "60.621200",
     "Urganch shahri, Al-Xorazmiy ko'chasi, 9"),
    ("xiva", "Xiva shahri", "Xiva Ichan Qal'a markazi", "41.377500", "60.364200",
     "Xiva shahri, Ichan Qal'a ko'chasi, 3"),
    ("fergana", "Farg'ona shahri", "Farg'ona markazi", "40.389400", "71.784300",
     "Farg'ona shahri, Amir Timur ko'chasi, 18"),
    ("namangan", "Namangan shahri", "Namangan Istiqlol markazi", "40.998300", "71.672600",
     "Namangan shahri, Istiqlol ko'chasi, 27"),
    ("andijon", "Andijon shahri", "Andijon markazi", "40.782100", "72.344200",
     "Andijon shahri, Erkinlik ko'chasi, 12"),
)

#: Tashkent districts used as the origin of the intercity rides.
CITY_ORIGIN_KEYS = ("sergeli", "yunusobod", "yuzeroy", "bektemir", "chilonzor", "markaz")

#: Intercity price range (so'm per seat), long rides cost noticeably more.
INTERCITY_PRICES = (
    95000, 120000, 145000, 160000, 185000, 210000, 240000, 265000, 290000, 320000, 350000,
    380000, 410000, 450000,
)

#: How many departures each regional destination gets.
INTERCITY_TRIPS_PER_DESTINATION = 2

#: Intercity requests created for every non-blocked passenger.
INTERCITY_REQUESTS_PER_PASSENGER = 2

ROUTES = (
    ("sergeli", "yunusobod"),
    ("markaz", "chirchiq"),
    ("yuzeroy", "yunusobod"),
    ("bektemir", "chilonzor"),
    ("zangiota", "sergeli"),
    ("chilonzor", "chirchiq"),
)

#: ``plan`` decides the subscription state: every value but ``pending`` and
#: ``expired`` is paid and activated through the payment service.
DRIVERS = (
    {
        "first_name": "Alisher", "last_name": "Karimov", "phone": "+998901110101",
        "plate": "01A 001AA", "brand": "Lacetti", "model": "Chery", "color": "white",
        "year": 2021, "seats_count": 4, "plan": "1 oy", "auto_renew": False,
        "bio": "Sergelidan Yunusobodga har kuni yuraman.",
    },
    {
        "first_name": "Bobur", "last_name": "Turgunov", "phone": "+998901110202",
        "plate": "01B 002BB", "brand": "Nexia", "model": "Daewoo", "color": "silver",
        "year": 2019, "seats_count": 4, "plan": "3 oy", "auto_renew": True,
        "bio": "Chilonzor - Yunusobod yo'nalishi bo'yicha ishlayman.",
    },
    {
        "first_name": "Sardor", "last_name": "Yo'ldoshev", "phone": "+998901110303",
        "plate": "01C 003CC", "brand": "Spark", "model": "Chery", "color": "blue",
        "year": 2022, "seats_count": 4, "plan": "1 oy", "auto_renew": False,
        "bio": "Yangi mashina, klima bilan.",
    },
    {
        "first_name": "Javlon", "last_name": "Rahimov", "phone": "+998901110404",
        "plate": "01D 004DD", "brand": "Cobalt", "model": "Chevrolet", "color": "black",
        "year": 2018, "seats_count": 4, "plan": "6 oy", "auto_renew": True,
        "bio": "Chirchiq - Toshkent yo'lida tez yuraman.",
    },
    {
        "first_name": "Otabek", "last_name": "Sultonov", "phone": "+998901110505",
        "plate": "01E 005EE", "brand": "Doblo", "model": "Hyundai", "color": "grey",
        "year": 2017, "seats_count": 4, "plan": "1 oy", "auto_renew": False,
        "bio": "Qisqa masofalar uchun tez va arzon.",
    },
    {
        "first_name": "Dilshod", "last_name": "Ergashev", "phone": "+998901110606",
        "plate": "01F 006FF", "brand": "Vito", "model": "Mercedes", "color": "white",
        "year": 2020, "seats_count": 9, "plan": "1 yil", "auto_renew": True,
        "bio": "Guruh bo'yicha sayohat uchun, 8 ta yo'lovchi o'rni bor.",
    },
)

PASSENGERS = (
    {"first_name": "Malika", "last_name": "Rahimova", "phone": "+998902220101"},
    {"first_name": "Aziz", "last_name": "Tursunov", "phone": "+998902220202"},
    {"first_name": "Nodira", "last_name": "Xolmatova", "phone": "+998902220303"},
    {"first_name": "Sardora", "last_name": "Yusupova", "phone": "+998902220404"},
    {"first_name": "Bekzod", "last_name": "Qodirov", "phone": "+998902220505"},
    {"first_name": "Dilnoza", "last_name": "Karimova", "phone": "+998902220606"},
    {"first_name": "Ulugbek", "last_name": "Tursunov", "phone": "+998902220707"},
    {"first_name": "Ozoda", "last_name": "Sharipova", "phone": "+998902220808"},
)

#: One account that both rides and drives, so the demo covers the BOTH role.
MIXED_ACCOUNT = {
    "first_name": "Sherzod", "last_name": "Aliyev", "phone": "+998902220909",
    "plate": "01G 007GG", "brand": "Cobalt", "model": "Chevrolet", "color": "red",
    "year": 2020, "seats_count": 4, "plan": "1 oy",
    "bio": "Kunning bir qismida haydovchi, bir qismida yo'lovchiman.",
}

#: Bought a subscription, never paid: the driver may not announce a ride yet.
PENDING_DRIVER = {
    "first_name": "Ulugbek", "last_name": "Nazarov", "phone": "+998901110707",
    "plate": "01H 008HH", "brand": "Matiz", "model": "Daewoo", "color": "grey",
    "year": 2015, "seats_count": 4, "plan": "1 oy",
    "bio": "Obunani to'lagan, tasdiqlash kutilmoqda.",
}

#: Paid long ago and let it lapse: the driver has no active subscription.
EXPIRED_DRIVER = {
    "first_name": "Kamron", "last_name": "Sa'dullaev", "phone": "+998901110808",
    "plate": "01I 009II", "brand": "Gentra", "model": "Hyundai", "color": "black",
    "year": 2016, "seats_count": 4, "plan": "3 oy",
    "bio": "Obunani uzaytirmoqchiman.",
}

PASSENGER_NOTES = (
    "",
    "Yukim bagajim bor, ikki kishilik joy kerak.",
    "Ishxonaga boraman, 08:00 da bo'lishim kerak.",
)

DRIVER_COMMENTS = (
    "Yo'l bo'ylab to'xtash mumkin.",
    "Faqat to'g'ri yo'nalish bo'yicha.",
    "Mashinada klima ishlaydi.",
    "Yuklash uchun bagajxonasi bor.",
)

#: A chat exchange used for the orders that are still open.
CHAT_OPENINGS = (
    "Assalomu alaykum, nechta o'rin kerak?",
    "Meningcha, yana 10 daqiqa kutamiz.",
    "Telefon raqamimni yozib qoldiring, kerak bo'lsa.",
)

CHAT_REPLIES = (
    "Salom, hozir javob beraman.",
    "Yaxshi, xarakat qilamiz.",
    "Chilonzor MFY oldida kutib turing, 5 daqiqada yetaman.",
    "Yukim joyini band qilib qo'ydim.",
)

REVIEW_SEED = (
    (5, "Haydovchi juda vaqtli keldi, mashina toza."),
    (4, "Yo'nalishni yaxshi biladi, tavsiya qilaman."),
    (4, "Xush ko'nmadi, rahmat."),
    (5, "Xotirjam va shaffof haydovchi."),
)

#: The minibus trip sells exactly 8 seats, so 4 orders of 2 fill it completely.
FULL_TRIP_SEATS_PER_ORDER = 2
FULL_TRIP_ORDERS = 4


@dataclass
class DriverAccount:
    user: object
    profile: DriverProfile
    vehicle: Vehicle
    subscription: object | None = None


@dataclass
class TripBundle:
    trip: DriverTrip
    driver: DriverAccount


@dataclass
class FinishedOrder:
    order: Order
    passenger: object
    driver: DriverAccount
    departed_at: object


@dataclass
class DemoData:
    locations: dict = field(default_factory=dict)
    plans: dict = field(default_factory=dict)
    admin: object = None
    drivers: list = field(default_factory=list)
    passengers: list = field(default_factory=list)
    users: list = field(default_factory=list)


class Command(BaseCommand):
    help = "Bazaga demo/test ma'lumotlarini qo'shadi (seed_testdata)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Avvalgi demo qatorlarini o'chirib, qaytadan yaratadi.",
        )
        parser.add_argument(
            "--scale",
            type=int,
            default=1,
            help="Yo'lovchilar sonining koefitsienti (1 = standart, 2 = ikki barobar).",
        )

    def handle(self, *args, **options):
        scale = max(1, int(options.get("scale") or 1))

        if options["flush"]:
            self._flush()
        elif self._demo_users().exists():
            raise CommandError(
                "Bazada allaqachon demo ma'lumot bor. Qayta yaratish uchun `--flush` "
                "argumentidan foydalaning."
            )

        data = self._seed_reference_data(scale)
        self._seed_transactions(data)
        self._report()

    # ------------------------------------------------------------------ utils
    def _log(self, message: str) -> None:
        self.stdout.write(f"  {message}")

    def _demo_users(self):
        return User.objects.filter(username__startswith=DEMO_PREFIX)

    def _backdate(self, instance, **fields):
        """Move an existing row into the past.

        ``auto_now_add`` columns cannot be written through ``save()``, and the
        transactional services only ever describe "now", so the history of the
        demo is applied as one explicit queryset update per row.
        """
        if not fields:
            return instance
        type(instance).objects.filter(pk=instance.pk).update(**fields)
        for name, value in fields.items():
            setattr(instance, name, value)
        return instance

    # ------------------------------------------------------- 1. reference data
    def _seed_reference_data(self, scale: int) -> DemoData:
        data = DemoData()
        data.locations = self._seed_catalogue()
        data.plans = self._seed_plans()
        data.admin = self._seed_admin()
        data.drivers, data.passengers = self._seed_accounts(data.plans, scale)
        ordered: list = []
        for account in data.drivers:
            ordered.append(account.user)
        ordered.extend(data.passengers)
        data.users = list({user.pk: user for user in ordered}.values())
        return data

    def _seed_catalogue(self) -> dict:
        regions = {
            spec["name"]: location_services.get_or_create_region(
                name=spec["name"], code=spec["code"]
            )
            for spec in REGIONS
        }
        districts = {
            name: location_services.get_or_create_district(region=regions[region], name=name)
            for region, name in DISTRICTS
        }

        locations = {}
        for key, district_name, name, latitude, longitude, address in LOCATIONS + REGION_LOCATIONS:
            locations[key] = location_services.get_or_create_location(
                district=districts[district_name],
                name=name,
                latitude=Decimal(latitude),
                longitude=Decimal(longitude),
                address=address,
            )

        checked_routes = ROUTES + tuple(
            (CITY_ORIGIN_KEYS[index % len(CITY_ORIGIN_KEYS)], destination_key)
            for index, (destination_key, *_rest) in enumerate(REGION_LOCATIONS)
        )
        for origin_key, destination_key in checked_routes:
            origin = locations[origin_key]
            destination = locations[destination_key]
            problem = ride_services.validate_route_points(
                (origin.latitude, origin.longitude),
                (destination.latitude, destination.longitude),
            )
            if problem:
                raise CommandError(
                    f"Demo marshrut {origin.name} -> {destination.name} yaroqsiz: {problem}"
                )

        self._log(
            f"katalog: {len(regions)} viloyat/shahar, {len(districts)} tuman, "
            f"{len(locations)} manzil"
        )
        return locations

    def _seed_plans(self) -> dict:
        plans = {}
        for spec in PLANS:
            plan = get_plan_queryset().filter(name=spec["name"]).first()
            if plan is None:
                plan = subscription_services.create_plan(
                    name=spec["name"],
                    duration_days=spec["duration_days"],
                    price=spec["price"],
                    description=spec["description"],
                )
            plans[spec["name"]] = plan
        self._log(f"obuna rejalari: {len(plans)}")
        return plans

    def _seed_admin(self):
        admin = User.objects.filter(username=ADMIN_USERNAME).first()
        if admin is None:
            admin = user_services.create_user(
                username=ADMIN_USERNAME,
                first_name="Support",
                last_name="Jamoasi",
                password=ADMIN_PASSWORD,
            )
        if not admin.is_staff or not admin.is_active:
            admin.is_staff = True
            admin.is_active = True
            admin.email = "demo_support@example.com"
            admin.save(update_fields=["is_staff", "is_active", "email", "updated_at"])
        self._log(f"support admin: {admin.username} / {ADMIN_PASSWORD}")
        return admin

    # ------------------------------------------------------------ 2. accounts
    def _driver_account(self, spec, index, *, role=UserRole.DRIVER) -> DriverAccount:
        username = f"{DEMO_PREFIX}{'haydovchi' if role == UserRole.DRIVER else 'aralash'}_{index}"
        user = user_services.create_user(
            username=username,
            telegram_id=900_000_000 + index,
            first_name=spec["first_name"],
            last_name=spec["last_name"],
            phone_number=spec["phone"],
            role=role,
        )
        profile = user_services.create_driver_profile(user, bio=spec["bio"])
        user_services.verify_driver_profile(profile, verified=True)
        vehicle = vehicle_services.create_vehicle(
            driver=profile,
            plate_number=spec["plate"],
            brand=spec["brand"],
            model=spec["model"],
            year=spec["year"],
            color=spec["color"],
            seats_count=spec["seats_count"],
        )
        vehicle_services.verify_vehicle(vehicle, verified=True)
        return DriverAccount(user=user, profile=profile, vehicle=vehicle)

    def _buy_subscription(self, account: DriverAccount, plan, *, auto_renew=False):
        subscription = subscription_services.create_subscription(
            driver=account.profile, plan=plan, auto_renew=auto_renew
        )
        payment = payment_services.create_payment(
            user=account.user,
            amount=plan.price,
            metadata={"subscription_id": subscription.pk, "plan_id": plan.pk},
        )
        payment_services.process_successful_payment(payment, verified=True)
        subscription.refresh_from_db()
        return subscription

    def _seed_accounts(self, plans, scale: int) -> tuple[list, list]:
        now = timezone.now()
        drivers = []

        for index, spec in enumerate(DRIVERS, start=1):
            account = self._driver_account(spec, index)
            account.subscription = self._buy_subscription(
                account, plans[spec["plan"]], auto_renew=spec["auto_renew"]
            )
            drivers.append(account)

        mixed = self._driver_account(
            MIXED_ACCOUNT, len(DRIVERS) + 1, role=UserRole.BOTH
        )
        mixed.subscription = self._buy_subscription(mixed, plans[MIXED_ACCOUNT["plan"]])
        drivers.append(mixed)

        unpaid = self._driver_account(PENDING_DRIVER, len(DRIVERS) + 2)
        unpaid.subscription = subscription_services.create_subscription(
            driver=unpaid.profile, plan=plans[PENDING_DRIVER["plan"]]
        )
        self._backdate(unpaid.subscription, created_at=now - timedelta(hours=5))
        drivers.append(unpaid)

        lapsed = self._driver_account(EXPIRED_DRIVER, len(DRIVERS) + 3)
        lapsed_plan = plans[EXPIRED_DRIVER["plan"]]
        lapsed_start = now - timedelta(days=lapsed_plan.duration_days + 30)
        lapsed.subscription = subscription_services.create_subscription(
            driver=lapsed.profile, plan=lapsed_plan
        )
        subscription_services.activate_subscription(
            lapsed.subscription, starts_at=lapsed_start
        )
        self._backdate(lapsed.subscription, created_at=lapsed_start, activated_at=lapsed_start)
        subscription_services.expire_due_subscriptions()
        lapsed.subscription.refresh_from_db()
        drivers.append(lapsed)

        passengers = []
        total = len(PASSENGERS) * scale
        for index in range(total):
            spec = PASSENGERS[index % len(PASSENGERS)]
            user = user_services.create_user(
                username=f"{DEMO_PREFIX}yolovchi_{index + 1}",
                telegram_id=910_000_000 + index,
                first_name=spec["first_name"],
                last_name=spec["last_name"],
                phone_number=spec["phone"],
                role=UserRole.PASSENGER,
            )
            self._backdate(user, created_at=now - timedelta(days=3 + index))
            user.last_seen_at = now - timedelta(hours=index + 1)
            user.save(update_fields=["last_seen_at", "updated_at"])
            passengers.append(user)
        passengers.append(mixed.user)

        blocked = user_services.create_user(
            username=f"{DEMO_PREFIX}bloklangan_1",
            telegram_id=930_000_001,
            first_name="Umid",
            last_name="Xolmatov",
            phone_number="+998902220123",
            role=UserRole.PASSENGER,
        )
        user_services.block_user(blocked)
        passengers.append(blocked)

        self._log(
            f"foydalanuvchilar: {len(drivers)} haydovchi "
            f"(1 aralash, 1 obunasi to'lanmagan, 1 obunasi tugagan), "
            f"{len(passengers)} yo'lovchi (1 bloklangan)"
        )
        return drivers, passengers

    # ----------------------------------------------------------- 3. journeys
    def _seed_transactions(self, data: DemoData) -> None:
        trips = self._seed_trips(data)
        finished = self._seed_orders(trips, data)
        self._seed_requests(data)
        self._seed_support_tickets(data)
        self._log_trip_summary(trips)

    def _new_trip(
        self,
        data,
        driver_index,
        route_index,
        *,
        depart_in,
        seats,
        price,
        publish=True,
        origin_key=None,
        destination_key=None,
        comment=None,
    ):
        driver = data.drivers[driver_index]
        if origin_key is None or destination_key is None:
            origin_key, destination_key = ROUTES[route_index % len(ROUTES)]
        trip = ride_services.create_trip(
            driver_profile=driver.profile,
            vehicle=driver.vehicle,
            from_location=data.locations[origin_key],
            to_location=data.locations[destination_key],
            departure_time=timezone.now() + depart_in,
            total_seats=seats,
            price_per_seat=Decimal(price),
            comment=comment or DRIVER_COMMENTS[route_index % len(DRIVER_COMMENTS)],
            publish=publish,
        )
        return TripBundle(trip=trip, driver=driver)

    def _seed_intercity_trips(self, data: DemoData) -> dict[str, TripBundle]:
        """Toshkent -> viloyat markazlariga yo'lovlar.

        Har bir viloyat markazi uchun bir nechta oldinga qaragan chiqish
        yaratiladi, haydovchilar esa mos ravishda aylanadi.
        """
        trips: dict[str, TripBundle] = {}
        drivers = data.drivers
        for index, (destination_key, *_rest) in enumerate(REGION_LOCATIONS):
            destination = data.locations[destination_key]
            for repeat in range(INTERCITY_TRIPS_PER_DESTINATION):
                driver_index = (index * INTERCITY_TRIPS_PER_DESTINATION + repeat) % len(drivers)
                driver = drivers[driver_index]
                depart_in = timedelta(hours=4 + index * 3 + repeat * 1.5, minutes=repeat * 25)
                price = INTERCITY_PRICES[index % len(INTERCITY_PRICES)]
                key = f"intercity_{destination_key}_{repeat}"
                trips[key] = self._new_trip(
                    data,
                    driver_index,
                    index,
                    depart_in=depart_in,
                    seats=driver.vehicle.seats_for_passengers,
                    price=price,
                    origin_key=CITY_ORIGIN_KEYS[index % len(CITY_ORIGIN_KEYS)],
                    destination_key=destination_key,
                    comment=f"Toshkentdan {destination.name} uchun umumiy yo'l. Nonushta va'da qilingan.",
                )
        return trips

    def _seed_trips(self, data: DemoData) -> dict:
        now = timezone.now()
        trips: dict[str, TripBundle] = {}

        upcoming = (
            (0, 0, 1, 3, "18000.00"),
            (1, 1, 2, 3, "25000.00"),
            (2, 2, 3, 3, "12000.00"),
            (3, 3, 4, 2, "15000.00"),
            (4, 4, 5, 3, "22000.00"),
            (5, 5, 6, 3, "40000.00"),
            (6, 0, 8, 3, "30000.00"),
        )
        for index, (driver_index, route_index, hours, seats, price) in enumerate(upcoming):
            trips[f"active_{index}"] = self._new_trip(
                data,
                driver_index,
                route_index,
                depart_in=timedelta(hours=hours),
                seats=seats,
                price=price,
            )

        for index in range(2):
            trips[f"draft_{index}"] = self._new_trip(
                data,
                driver_index=index * 4,
                route_index=index + 2,
                depart_in=timedelta(hours=12 + index * 2),
                seats=3,
                price="20000.00",
                publish=False,
            )

        trips["full"] = self._new_trip(
            data, 5, 0, depart_in=timedelta(hours=3), seats=8, price="50000.00"
        )

        expired = self._new_trip(
            data, 3, 5, depart_in=timedelta(hours=-15), seats=3, price="35000.00"
        )
        self._backdate(expired.trip, created_at=now - timedelta(hours=26))
        ride_services.expire_trips(grace_minutes=0)
        expired.trip.refresh_from_db()
        trips["expired"] = expired

        completed = self._new_trip(
            data, 1, 1, depart_in=timedelta(hours=-6), seats=3, price="20000.00"
        )
        self._backdate(
            completed.trip,
            created_at=now - timedelta(hours=14),
            departure_time=now - timedelta(hours=6),
        )
        trips["completed"] = completed

        running = self._new_trip(
            data, 2, 3, depart_in=timedelta(hours=-3), seats=3, price="14000.00"
        )
        self._backdate(
            running.trip, created_at=now - timedelta(hours=9), departure_time=now - timedelta(hours=3)
        )
        trips["in_progress"] = running

        cancelled = self._new_trip(
            data, 6, 4, depart_in=timedelta(hours=4), seats=3, price="17000.00"
        )
        ride_services.cancel_trip(cancelled.trip, reason="Mashinada nosozlik paydo bo'ldi.")
        cancelled.trip.refresh_from_db()
        self._backdate(
            cancelled.trip,
            created_at=now - timedelta(days=2),
            departure_time=now - timedelta(days=1),
        )
        trips["cancelled"] = cancelled

        intercity = self._seed_intercity_trips(data)
        trips.update(intercity)

        self._log(f"yo'lovlar: {len(trips)} (shundan Toshkent -> viloyat: {len(intercity)})")
        return trips

    def _log_trip_summary(self, trips: dict) -> None:
        labels = {
            "active": "faol",
            "full": "to'liq",
            "draft": "qoralama",
            "completed": "yakunlangan",
            "in_progress": "yo'lga chiqdi",
            "expired": "muddati tugagan",
            "cancelled": "bekor qilingan",
        }
        summary: dict[str, int] = {}
        for bundle in trips.values():
            bundle.trip.refresh_from_db()
            label = labels.get(bundle.trip.status, bundle.trip.status)
            summary[label] = summary.get(label, 0) + 1
        self._log(
            "yo'lovlar holati: "
            + ", ".join(f"{name} - {count}" for name, count in sorted(summary.items()))
        )

    # ------------------------------------------------------------ 4. orders
    def _create_order(self, bundle: TripBundle, passenger, index, *, seats=1, note=None):
        companion = None
        if index % 3 == 0:
            companion = {
                "first_name": "Jasur",
                "last_name": "Ortiqov",
                "phone_number": "+998935554433",
            }
        return order_services.create_order(
            passenger=passenger,
            trip=bundle.trip,
            seats_booked=seats,
            passenger_note=PASSENGER_NOTES[index % len(PASSENGER_NOTES)] if note is None else note,
            companion=companion,
        )

    def _chat(self, order, passenger, driver_user, opening, reply, *, moment=None):
        thread = chat_services.get_or_create_thread(order)
        first = chat_services.send_message(thread=thread, sender=passenger, text=opening)
        second = chat_services.send_message(thread=thread, sender=driver_user, text=reply)
        if moment is None:
            return thread

        self._backdate(
            first,
            created_at=moment - timedelta(minutes=18),
            updated_at=moment - timedelta(minutes=18),
        )
        self._backdate(
            second,
            created_at=moment - timedelta(minutes=2),
            updated_at=moment - timedelta(minutes=2),
        )
        self._backdate(
            thread,
            last_message_at=second.created_at,
            last_message_preview=second.text[:120],
            created_at=moment - timedelta(minutes=20),
        )
        return thread

    def _seed_orders(self, trips: dict, data: DemoData) -> list[FinishedOrder]:
        now = timezone.now()
        passengers = data.passengers[: len(PASSENGERS)]
        finished: list[FinishedOrder] = []

        pending = (
            ("active_0", 0, 2, 3),
            ("active_1", 1, 1, 3),
            ("active_2", 2, 2, 2),
            ("full", 3, 1, 4),
        )
        for order_index, (trip_key, passenger_index, seats, minutes_ago) in enumerate(pending):
            bundle = trips[trip_key]
            passenger = passengers[passenger_index]
            order = self._create_order(bundle, passenger, passenger_index, seats=seats)
            self._chat(
                order,
                passenger,
                bundle.driver.user,
                CHAT_OPENINGS[order_index % len(CHAT_OPENINGS)],
                CHAT_REPLIES[order_index % len(CHAT_REPLIES)],
                moment=now - timedelta(minutes=minutes_ago),
            )
            self._backdate(order, created_at=now - timedelta(minutes=minutes_ago + 5))

        full = trips["full"]
        full_orders = [
            self._create_order(full, passengers[index], index, seats=FULL_TRIP_SEATS_PER_ORDER)
            for index in range(FULL_TRIP_ORDERS)
        ]
        for offset, order in enumerate(full_orders):
            order = order_services.accept_order(order)
            self._chat(
                order,
                order.passenger,
                full.driver.user,
                "Yakka ketaman, ko'p yukim yo'q.",
                "Joyni band qilib qo'ydim, ko'zingizni tuting.",
                moment=now - timedelta(hours=4, minutes=5 - offset * 2),
            )
            self._backdate(
                order,
                created_at=now - timedelta(hours=4, minutes=10 - offset * 2),
                accepted_at=now - timedelta(hours=4, minutes=offset * 2),
            )
        full.trip.refresh_from_db()
        self._backdate(full.trip, created_at=now - timedelta(hours=5))

        accepted_specs = (
            ("active_3", 0, 1),
            ("active_5", 1, 1),
        )
        for trip_key, passenger_index, seats in accepted_specs:
            bundle = trips[trip_key]
            passenger = passengers[passenger_index]
            order = self._create_order(bundle, passenger, passenger_index, seats=seats)
            order = order_services.accept_order(order)
            self._chat(
                order,
                passenger,
                bundle.driver.user,
                "Yana bitta joy bormi? Yo'ldan chiqmayman.",
                "Bor, sizga qo'shdim.",
            )

        arrived = trips["active_4"]
        arrived_order = self._create_order(arrived, passengers[2], 2, seats=1)
        arrived_order = order_services.accept_order(arrived_order)
        arrived_order = order_services.mark_driver_arrived(arrived_order)
        self._chat(
            arrived_order,
            arrived_order.passenger,
            arrived.driver.user,
            "Menga qarab yurib turing, 2 daqiqa.",
            "Manzilga yetib bo'ldim, ko'taraman.",
        )

        running = trips["in_progress"]
        running_order = self._create_order(running, passengers[3], 3, seats=1)
        running_order = order_services.accept_order(running_order)
        running_order = order_services.mark_driver_arrived(running_order)
        ride_services.start_trip(running.trip)
        running.trip.refresh_from_db()
        running_order = order_services.start_order(running_order)
        self._chat(
            running_order,
            running_order.passenger,
            running.driver.user,
            "Xabar bering, qayerdasiz?",
            "Yo'lga chiqdik, 40 daqiqa yetadi.",
            moment=running.trip.departure_time,
        )
        self._backdate(
            running_order, created_at=running.trip.departure_time - timedelta(hours=5)
        )

        rejected = trips["active_5"]
        rejected_order = self._create_order(rejected, passengers[4], 4, seats=1)
        order_services.reject_order(rejected_order, reason="Yo'nalish mos kelmadi, uzr.")

        dropped = trips["active_6"]
        dropped_order = self._create_order(dropped, passengers[5], 5, seats=2)
        order_services.cancel_order_by_passenger(
            dropped_order, reason="Reja o'zgardi, keyinroq buyurtma qilaman."
        )

        late = trips["active_1"]
        late_order = self._create_order(late, passengers[6], 6, seats=1)
        late_order = order_services.accept_order(late_order)
        order_services.cancel_order_by_driver(
            late_order, reason="Yo'lovchi ko'rinmadi, bekor qildim."
        )

        no_show_bundle = trips["active_2"]
        no_show_order = self._create_order(no_show_bundle, passengers[7], 7, seats=1)
        no_show_order = order_services.accept_order(no_show_order)
        order_services.mark_no_show(no_show_order, reason="Yo'lovchi 15 daqiqa kutdi.")

        completed = trips["completed"]
        completed_specs = ((1, 1), (2, 1), (3, 1))
        for passenger_index, seats in completed_specs:
            passenger = passengers[passenger_index]
            departed_at = completed.trip.departure_time
            order = self._create_order(completed, passenger, passenger_index, seats=seats)
            order = order_services.accept_order(order)
            self._chat(
                order,
                passenger,
                completed.driver.user,
                CHAT_OPENINGS[passenger_index % len(CHAT_OPENINGS)],
                CHAT_REPLIES[passenger_index % len(CHAT_REPLIES)],
                moment=departed_at - timedelta(minutes=20),
            )
            order = order_services.mark_driver_arrived(order)
            order = order_services.start_order(order)
            order = order_services.complete_order(order)
            self._backdate(
                order,
                created_at=departed_at - timedelta(hours=5),
                accepted_at=departed_at - timedelta(hours=4, minutes=45),
                completed_at=departed_at,
            )
            finished.append(
                FinishedOrder(
                    order=order,
                    passenger=passenger,
                    driver=completed.driver,
                    departed_at=departed_at,
                )
            )

        ride_services.complete_trip(completed.trip)
        completed.trip.refresh_from_db()
        self._seed_reviews(finished)
        self._log(f"buyurtmalar: {self._count_orders()} | baholashlar: {self._count_reviews()}")
        return finished

    def _seed_reviews(self, finished: list[FinishedOrder]) -> None:
        for index, item in enumerate(finished):
            rating, comment = REVIEW_SEED[index % len(REVIEW_SEED)]
            review = review_services.create_review(
                order=item.order,
                reviewer=item.passenger,
                reviewed_user=item.driver.user,
                rating=rating,
                comment=comment,
            )
            self._backdate(review, created_at=item.departed_at + timedelta(hours=1))
            if index % 2 == 0:
                answer = review_services.create_review(
                    order=item.order,
                    reviewer=item.driver.user,
                    reviewed_user=item.passenger,
                    rating=5,
                    comment="Yo'lovchi vaqtida keldi, xush muomala.",
                )
                self._backdate(
                    answer, created_at=item.departed_at + timedelta(hours=1, minutes=10)
                )

    # ----------------------------------------------- 5. passenger requests
    def _seed_requests(self, data: DemoData) -> None:
        now = timezone.now()
        passengers = data.passengers[: len(PASSENGERS)]

        stale = ride_services.create_passenger_request(
            passenger=passengers[3],
            from_location=data.locations["bektemir"],
            to_location=data.locations["chilonzor"],
            passenger_count=1,
            max_price_per_seat=Decimal("15000.00"),
            departure_from=now - timedelta(hours=30),
            departure_until=now - timedelta(hours=24),
            comment="Eski so'rov, muddati o'tib ketgan.",
        )
        self._backdate(stale, created_at=now - timedelta(days=2))
        ride_services.expire_passenger_requests(expiry_hours=0)
        stale.refresh_from_db()

        active_specs = (
            ("sergeli", "yunusobod", 0, 2, "25000.00", "Bugun kechqurun 18:00 dan keyin."),
            ("markaz", "chirchiq", 1, 1, "45000.00", "Erta tong 07:00 da kerak."),
            ("yuzeroy", "yunusobod", 2, 4, "18000.00", "Oilaviy, ikki kishilik joy kerak."),
        )
        created = [stale]
        for index, (origin_key, destination_key, passenger_index, count, price, comment) in enumerate(
            active_specs
        ):
            departure_from = now + timedelta(hours=2 + index)
            request = ride_services.create_passenger_request(
                passenger=passengers[passenger_index],
                from_location=data.locations[origin_key],
                to_location=data.locations[destination_key],
                passenger_count=count,
                max_price_per_seat=Decimal(price),
                departure_from=departure_from,
                departure_until=departure_from + timedelta(hours=6),
                comment=comment,
            )
            self._backdate(request, created_at=now - timedelta(minutes=45 - index * 10))
            created.append(request)

        # Har bir bloklanmagan foydalanuvchi (haydovchilar ham) uchun
        # Toshkent -> viloyat so'rovi.
        intercity_passengers = [
            user for user in data.users if not user.is_blocked and not user.is_staff
        ]
        region_keys = [key for key, *_rest in REGION_LOCATIONS]
        for index, passenger in enumerate(intercity_passengers):
            for slot in range(INTERCITY_REQUESTS_PER_PASSENGER):
                region_index = (index + slot * len(intercity_passengers)) % len(region_keys)
                destination_key = region_keys[region_index]
                origin_key = CITY_ORIGIN_KEYS[(index + slot) % len(CITY_ORIGIN_KEYS)]
                departure_from = now + timedelta(days=1 + slot, hours=6 + index % 8)
                request = ride_services.create_passenger_request(
                    passenger=passenger,
                    from_location=data.locations[origin_key],
                    to_location=data.locations[destination_key],
                    passenger_count=1 + (index + slot) % 4,
                    max_price_per_seat=Decimal(
                        INTERCITY_PRICES[region_index % len(INTERCITY_PRICES)]
                    ),
                    departure_from=departure_from,
                    departure_until=departure_from + timedelta(days=2),
                    comment=f"{data.locations[origin_key].name}dan {data.locations[destination_key].name}ga "
                    "uchish kerak, haydovchi qidiraman.",
                )
                self._backdate(request, created_at=now - timedelta(minutes=25 - slot * 5))
                created.append(request)

        statuses = Counter(request.status for request in created)
        self._log(
            "yo'lovchi so'rovlari: "
            f"{len(created)} ({', '.join(f'{name} - {count}' for name, count in sorted(statuses.items()))}), "
            f"{len(intercity_passengers)} foydalanuvchida viloyatga so'rov bor"
        )

    # ------------------------------------------------------- 6. support desk
    def _seed_support_tickets(self, data: DemoData) -> None:
        now = timezone.now()
        passengers = data.passengers[: len(PASSENGERS)]
        specs = (
            (0, "To'lovni qaytarib olishim mumkinmi?", "payment", "high", "closed"),
            (1, "Obunam ertaga tugaydi, qanday davom ettiraman?", "subscription", "normal", "in_progress"),
            (2, "Mashinam tasdiqlanmagan ko'rinmoqda.", "verification", "normal", "open"),
        )
        for index, (passenger_index, subject, category, priority, status) in enumerate(specs):
            passenger = passengers[passenger_index]
            opened_at = now - timedelta(days=index + 1)
            ticket = support_services.create_ticket(
                user=passenger,
                subject=subject,
                category=category,
                priority=priority,
            )
            support_services.add_message(
                ticket=ticket, sender=passenger, body="Assalomu alaykum, iltimos yordam bering."
            )
            if status in {"in_progress", "closed"}:
                support_services.add_message(
                    ticket=ticket,
                    sender=data.admin,
                    body="Salom! Murojaatingiz ko'rib chiqilmoqda, javobni tez orada beramiz.",
                    is_from_support=True,
                )
                support_services.set_ticket_status(
                    ticket, "in_progress" if status == "in_progress" else "closed", actor=data.admin
                )
            if status == "closed":
                support_services.add_message(
                    ticket=ticket,
                    sender=data.admin,
                    body="Murojaat yopildi. Yana yordam kerak bo'lsa yangi murojaat yarating.",
                    is_from_support=True,
                )

            messages = list(ticket.messages.order_by("id"))
            for offset, message in enumerate(messages):
                moment = opened_at + timedelta(hours=offset)
                self._backdate(message, created_at=moment, updated_at=moment)
            self._backdate(
                ticket,
                created_at=opened_at,
                last_message_at=messages[-1].created_at,
            )
        self._log(f"support murojaatlari: {len(specs)}")

    # ------------------------------------------------------------- 7. flush
    def _flush(self) -> None:
        owner = f"{DEMO_PREFIX}%"
        demo_orders = Order.objects.filter(passenger__username__startswith=DEMO_PREFIX)
        demo_trips = DriverTrip.objects.filter(driver__user__username__startswith=DEMO_PREFIX)
        demo_users = self._demo_users()

        counts = (
            ("baholashlar", Review.objects.filter(order__passenger__username__startswith=DEMO_PREFIX)),
            ("suhbatlar", ChatThread.objects.filter(order__passenger__username__startswith=DEMO_PREFIX)),
            ("murojaat xabarlari", SupportMessage.objects.filter(ticket__user__username__startswith=DEMO_PREFIX)),
            ("murojaatlar", SupportTicket.objects.filter(user__username__startswith=DEMO_PREFIX)),
            ("bildirishnomalar", Notification.objects.filter(user__username__startswith=DEMO_PREFIX)),
            ("buyurtmalar", demo_orders),
            ("yo'lovlar", demo_trips),
            ("yo'lovchi so'rovlari", PassengerRequest.objects.filter(passenger__username__startswith=DEMO_PREFIX)),
            ("obunalar", DriverSubscription.objects.filter(driver__user__username__startswith=DEMO_PREFIX)),
            ("to'lovlar", Payment.objects.filter(user__username__startswith=DEMO_PREFIX)),
            ("avtomobillar", Vehicle.objects.filter(driver__user__username__startswith=DEMO_PREFIX)),
            ("haydovchi profillari", DriverProfile.objects.filter(user__username__startswith=DEMO_PREFIX)),
            ("foydalanuvchilar", demo_users),
        )
        removed = 0
        for label, queryset in counts:
            deleted, _ = queryset.delete()
            if deleted:
                removed += deleted
                self.stdout.write(f"  o'chirildi: {label} - {deleted}")

        self._log(
            f"eski demo ma'lumot tozalandi ({removed} qator, foydalanuvchilar: {owner})"
        )

    # ------------------------------------------------------------ 8. report
    def _count(self, model, field_path: str) -> int:
        return model.objects.filter(**{f"{field_path}__startswith": DEMO_PREFIX}).count()

    def _count_orders(self) -> int:
        return Order.objects.filter(passenger__username__startswith=DEMO_PREFIX).count()

    def _count_reviews(self) -> int:
        return Review.objects.filter(reviewer__username__startswith=DEMO_PREFIX).count()

    def _report(self) -> None:
        rows = (
            ("Foydalanuvchilar", self._demo_users().count()),
            ("Yo'lovlar", self._count(DriverTrip, "driver__user__username")),
            ("Yo'lovchi so'rovlari", self._count(PassengerRequest, "passenger__username")),
            ("Buyurtmalar", self._count_orders()),
            ("Chat xabarlari", self._count(ChatMessage, "thread__order__passenger__username")),
            ("Baholashlar", self._count_reviews()),
            ("Obunalar", self._count(DriverSubscription, "driver__user__username")),
            ("To'lovlar", self._count(Payment, "user__username")),
            ("Bildirishnomalar", self._count(Notification, "user__username")),
            ("Support murojaatlari", self._count(SupportTicket, "user__username")),
        )
        self.stdout.write(self.style.SUCCESS("\nDemo ma'lumot tayyor:"))
        for label, count in rows:
            self.stdout.write(f"  {label}: {count}")
        driver = User.objects.filter(username=f"{DEMO_PREFIX}haydovchi_1").first()
        passenger = User.objects.filter(username=f"{DEMO_PREFIX}yolovchi_1").first()
        self.stdout.write(
            f"\nDjango admin: {ADMIN_USERNAME} / {ADMIN_PASSWORD}"
            f"\nBot uchun telegram_id: haydovchi {driver.telegram_id}, "
            f"yo'lovchi {passenger.telegram_id}"
        )
