from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "exchange_rate" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "date" DATE NOT NULL UNIQUE,
    "cny_krw" DECIMAL(12,4) NOT NULL,
    "source" VARCHAR(50) NOT NULL
);
COMMENT ON TABLE "exchange_rate" IS '외부 API 에서 받은 위안 환율 캐시 — 하루 1건. 외부 API 가 죽어도 마지막 값으로 계산한다.';
        CREATE TABLE IF NOT EXISTS "product_pricing" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "platform" VARCHAR(20) NOT NULL,
    "fx_rate" DECIMAL(12,4) NOT NULL,
    "fx_date" DATE NOT NULL,
    "fx_markup_pct" DECIMAL(5,2) NOT NULL,
    "shipping_fee" INT NOT NULL,
    "platform_fee_rate" DECIMAL(5,2) NOT NULL,
    "payment_fee_rate" DECIMAL(5,2) NOT NULL,
    "product_id" INT NOT NULL REFERENCES "product" ("id") ON DELETE CASCADE,
    "survey_id" INT NOT NULL REFERENCES "price_survey" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_product_pri_product_a7911c" UNIQUE ("product_id", "platform")
);
COMMENT ON COLUMN "product_pricing"."platform" IS 'COUPANG: coupang\nNAVER: naver';
COMMENT ON TABLE "product_pricing" IS '제품 1개의 판매처별 가격 설정. 제품 1 : 판매처별 1개.';
        CREATE TABLE IF NOT EXISTS "option_price" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "sale_price" INT NOT NULL,
    "option_id" INT NOT NULL REFERENCES "price_survey_option" ("id") ON DELETE CASCADE,
    "pricing_id" INT NOT NULL REFERENCES "product_pricing" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_option_pric_pricing_2edece" UNIQUE ("pricing_id", "option_id")
);
COMMENT ON TABLE "option_price" IS '옵션 1개의 판매처별 판매가 (원).';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "product_pricing";
        DROP TABLE IF EXISTS "exchange_rate";
        DROP TABLE IF EXISTS "option_price";"""


MODELS_STATE = (
    "eJztXWtzmzoa/iuMvzSZTbMYg407251x0vScbNMkk7rdzmnOMELIMRMbOFyaZM72v68uYK"
    "4m4NixwfqSGNArxCMh6X3eC3935raBZt7xtWsbAfQ774S/OxaYI/wje+lI6ADHiS+QEz7Q"
    "Z7Sskyike74LaF0TMPMQPmUgD7qm45u2RQrfBlDtwtvAkFVVuA0ksSvjf0avK94G+hDJ+L"
    "fSF/EpKMJuWAz/B3AgHwsZYThRcHldNiA5MIYyKSfiiuBgAIX3AnQR8JGhAf+YNM6wIW6d"
    "ad1tuR2BZf4VIM2375A/RS5uzY8/8WnTMtAj8qJD516bmGhmpLrFNEgF9LzmPzn03Lnlf6"
    "QFySPqGrRnwdyKCztP/tS2FqVNi3bUHbKQSxqFz/luQDrKCmazsEujvmMtjYuwJiZkDDQB"
    "wYx0N5FmDYjPdTTt8mqsfTkba1onNxQiiUSvhKegbZFhhJvq0ae/I014K3Xlgaz2+rKKi9"
    "BmLs4MfrFbx8AwQQrP5bjzi14HPmAlKMYxqHH35MH9gK/45hwVI5yWzCBthKLH0Y8s7hHK"
    "ZcBHJ2Lk4/fqNaDHD2hcWbOnsMtLcB6ffz77Mh59via3m3veXzOK32h8Rq5I9OxT5uxB/5"
    "Cct/GUwaaSRSXCf8/HvwvkUPjj6vKMwmt7/p1L7xiXG//RIW0CgW9rlv2gASMxOqOzEWq4"
    "ZNzrgWOs2OtpSd7ru9LrEUaJbg9bn3jX8fKV7+/TKXCXvOFh+UwvY7RW6dftTqNz8KjNkH"
    "XnT/GhIpb06rfRzenvo5sDRcz01GV4RaKXfqWgdaY2xj1wZ3XwTQmtBHII4c68OymUu6JY"
    "BWdSbCnS7GIaa9/0Z0iDVh2okzLrGc47BXWvEtK9EqB7y3C+t+vjzGTaN6I3AjNWKdBqa3"
    "Facg1r8Y6B39yll+24iCYzuU9su8kJHcD7B+AaWupKYiVxTYg0L3B/oicvPyJOQvGPn27Q"
    "DFBE832/UGBxVV9oTQ2c4X5Fwz06W7SlIWjhSl4MFFXir1llbcKKjDhbspeNwfyluTTPng"
    "EWuKOPRO5N7lQwvArpk9ToK6NQ4hFflUdhFAOAYEj5iAHhG0QAYzIjwVFQ5oIc6cMBKWFI"
    "+pAWUPCBLgIiOzTwdagYYqo6woMoRASgHqFGVMXI8B9d4V26AZdFbMsOt/bWwj/7PQX/7S"
    "qUzzG6Bi2kKqQNior/SkPWSEbrAIXeSSUNgbQJigxIq5Eo2LSPPCF6CCh1VdoUyg51e+S5"
    "JCQLB/i/ErYSFtatgwG9qUToKPIMQrahtGrYl1kTdEI8IVFnIIXXyb+BqrKbHnICihNQTZ"
    "rVG0pFcAJqH3udE1BbJaDY9kkj4774jSpGOCNW9jo18FUqAZm8DpzD2x6HB2wd1AY7LdVC"
    "Hm9TcEM7cIB1p81NS6PqVo2NbKHs8/vaBoz0texs8yDXHNQZMT6HVB3UFviJ3JWGdIEkH9"
    "D5Ac1gqjmcU0J8MFcdzNwK0FYrQJqupkSzVotJSgutNFHt3K5nDTNVzrqSgzmP8UfbRead"
    "9Qk9UajPcaOAVbgA5H0AGwbxMpMAPu2ChwW7mRldGAE2n9BJfvTldPQBq0lV7FYh87s2i9"
    "WVExVtCfDcblUDq1eyW11FLS6zXsUjsZoNS7NjgUouwTkDTsLOEZqDFmYbQ+kPhX8Q+4ox"
    "UYWkaYnaevqiepiqoPueevEOmS+v8IaUVUVmUHpzlCoqvY+aAQcDYnQZqqrw5gKX6g2Ph9"
    "SkMhBlau5Ri32Km/og3CbEbUINmTEbah3gNqF97PUqNiG2WHbrUAwJkRZywFIlgkEq4Rek"
    "PL3AIJPqoyy1k8bZCMhsEwitp4L5C0FzDmbLFPyEXHb2YoLHYQUNHN1lRriz0/PPo4uDrn"
    "QkUaDxvGQy3TPqApm72m+RlQwVmlqb3JQMZ6ueZ6tiz8cXk1Vt9Pc9yhBWqfG1Ol9FJ90X"
    "8i+MGbiObEgtAXyj5MvZI5wC6w7dANpnOd4ldf2ojHJBYUnNjYpWIVv6A+INaqiiMLo+F5"
    "gXLWENKDOhw65OyAE5zREQL9w+9XcdSNSlFA2JjGQkPHhDp1UVpSOls7cjLAelQCZG5LSq"
    "9yCpQB/C0KOW/h4yF1qJ3JR6zTI/WQAhaZSoi4xjYZ6thWxMe5+U0zWcrmnIHNtQxZ3TNf"
    "vY61XomroOppvyLN3qhFrPrxQr9tq9+1CTFEhI7SklIFemBDw7cIscwJbzAbFECxnE9XiX"
    "14he3aTCkNSxCvSFjAq2XF1gdGbs8FdNW8iaL8kmlUafJZMlQTgke18Is1mU6B74gNRjiI"
    "fFm/R136Bgb/wj8jag/c0e70++YeYb5p2cyZq5deIb5n3s9SobZg/MUG0H9bQQJ9ELnNPD"
    "9bzW+pSS4agWoBruFOo6KCeFOK5VHJQXG7L1OCi3zwX0KOennBxkxXaf/PywXqta63ySsy"
    "CnJsi6trXN+uymhvnybL2JF+HZpL1a4jWsmby3sraWTv3SlVgyE6UwMcuSSsJ7PZPGdxst"
    "osljoETtRQOsyIqiPkjYd2RmR4rtTBUSyBTot6xegWm5uXMsC0yYZgauaj/6kYwZcWbAn9"
    "junGvJXEvezfm8ofoS15L3sderaMmLKTfX54TDP7OCeW63llZBEvK7zOh3Tq++Xo8uf3sn"
    "hGH/t9bl6NvZDa6LxE1nl/hqrqyVPFlLHFmz5pTJ48KnpobBKiHFDVbPGKwwVnUNqQmRvc"
    "7Sg3GYA/c+cDSnKML3uSGalt3OQBW3N0qVGo7W3tR0HKJyT1At7jIj9np8EPFg3hS2ayfa"
    "wgWLoLTKbFsov4/zbp0R7YCnObL8lTEvEOczSBnePN3FRiYPHpaxLlR5EpFXSyKSH8DrJe"
    "dbDO+aQl6SLlA88uW1I19GjvmpOFN+eOWozGQBHFO7r54fHw5I4IbeM4Y0ooMw4X0wDEMz"
    "DBGwDOxDmiOjS60GcKgK3r05m5EIDXnSPTymsR6Ixm0osvD9LRZ+i9spLCh2FkRCssOXhK"
    "FspSEsqz2xFuh6LzZA6NRAApA4XHzhUFdkKCzyleiQJosfQnYwoWExCNIwFhhaKD6cLIJp"
    "aGJ8bwokpU/roMlGJAPGVchK1KTwcVmbFzn12QFJgUJtKCqza7jIQ8CFU5odRYULAwarFM"
    "qTKP99Kr+9cADx9PlPEPhT/Mo43rHzxFPec8NGo2bmhlLc3LCxj71exbBB/+f6uyx96ryt"
    "YQndqjkKylIUZCkGvCfCG1o0MR/roJyWaiPW/SpQZ9+LBNL9IqCnwJvWhTmSad03HPpyBY"
    "j78lKIyaU0xHhPb/4smC1ObHuGgFWMcSyUQVjHUpsaxxHqr0tBnlxdXaSm/ZPzcQbdr59P"
    "zvDAzjCUeQZtBjxfC7yVluOsLE+5vDvrb8G2y0NuPaY0IcF50ud5UgLXGpi8r2E1DQO3Ko"
    "WXGFS75FdLUS+gpKLeKCOkHC3q+iqMVJbpiF00yacND6KMrfpAhZTxgQoyGEsT0jeE3Dh2"
    "kDs3PY9kmj6+watimDukiHna/A05r8J5lYZMUw3VsDmvso+9XoVXIUtPXW4lKdM6dXT9nx"
    "Tk1NUGwXWA5z3YePtWl1PJCbYQ7o0whS7evdUBOirfQnzX7zLOqatXo648RNUR7SdyvcII"
    "1+UuYHnJV3TO3WGlokaqo8SQZx4ZL3SkiX0/GjajLPWhSaU+C/UqaM8dYD1pWAG3A1LBiz"
    "A7ZbWNWGWNpVef+UJUtM7/NNHDWgG7Dmv+hitu08DbJE+WGXIFjFl+UC7nzjKvQ1UKzegT"
    "XyBGW0XpdeWJuHAmSuTgjbypdCRTnyQg5+gvQyQJeGGfBIDrsCtHv1kQN5wgEjjdk7qLsG"
    "4WKk6/qKRDVV64ZxVwbzvcUk7acdKuITNdQ+kbTtrtY69XIe3Ko7zLA91aqopvhOqY2Xdm"
    "cWq05TgnZVqI82Y++BTt0ZEF81iP0eOyELeMXCvwLpunzr6PU1NUhOrB59H3w9Q0dXF1+V"
    "tUPNELpxdXJxnwAw9v1QsUo/98ubpcxv9HEtllw4S+8D9hZnoboz86/5oEFiSYCnpgznzT"
    "8o7J/f7def3uIAiVd0cW+cxSQCrIdke0G9NrxiXm5FaipHZMw9+wy02MWR7oTTne7BjCVf"
    "1ucsMr5X2DWyFcfr24qPjJKE7J7Cwlk0LwWXomi3dlqkZLjYGqxA3jNnSaeI+FmBn9Hg3e"
    "UkiIGXFBIqQH6onUbcmIP7akS2KYBo9+4lrRVZal7yBWfg/DKzTQjH7dOmZPqCcTrceQ5C"
    "hCjiTdow5PQ0arkAx5qUR85RF9zX4YTv9w+qchs2pDiQBO/+xjr1ehf0ynDiHBSrfvW72b"
    "iBtie5NaC1RaiAc6FHha8NCRDeuxCfvnC5XY2i4Bu4Z0VX02/do+n2mHR+e8JDrnBi95N+"
    "en422F54yQa8JppyhnDLtyVBqiE5d5TkldjihXmHZLYVrq9rd8J7Xc36+ZloaMZUdRqlh2"
    "FGW5ZYdcy2ypnFp71bB4C9HdiH0S39FHRev+cttNQuT1jTfbsZqtzUxTw711/YvZr/8DG4"
    "Wo+g=="
)
