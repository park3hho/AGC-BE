from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "taobao_purchase" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "taobao_order_no" VARCHAR(40),
    "shop_name" VARCHAR(200),
    "item_url" VARCHAR(500),
    "items" JSONB NOT NULL,
    "paid_cny" DECIMAL(12,2),
    "purchased_at" TIMESTAMPTZ,
    "cn_status" VARCHAR(20) NOT NULL,
    "shipped_at" TIMESTAMPTZ,
    "cn_courier" VARCHAR(50),
    "cn_tracking_no" VARCHAR(60),
    "arrived_at" TIMESTAMPTZ,
    "warehouse_ref" VARCHAR(60),
    "status_source" VARCHAR(10) NOT NULL,
    "status_checked_at" TIMESTAMPTZ,
    "memo" TEXT,
    "deleted_at" TIMESTAMPTZ,
    "created_by_id" INT REFERENCES "app_user" ("id") ON DELETE SET NULL,
    "purchased_by_id" INT REFERENCES "app_user" ("id") ON DELETE SET NULL
);
COMMENT ON TABLE "taobao_purchase" IS '타오바오 구매 1건 = 타오바오 주문번호 1개 (판매처 1곳) + 그 물건이 집운 창고까지 오는 중국 내 배송.';
        CREATE TABLE IF NOT EXISTS "taobao_purchase_link" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "quantity" INT,
    "order_id" INT NOT NULL REFERENCES "market_order" ("id") ON DELETE RESTRICT,
    "purchase_id" INT NOT NULL REFERENCES "taobao_purchase" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_taobao_purc_purchas_631384" UNIQUE ("purchase_id", "order_id")
);
COMMENT ON TABLE "taobao_purchase_link" IS '타오바오 구매 ↔ 마켓 주문 연결 (다대다).';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "taobao_purchase";
        DROP TABLE IF EXISTS "taobao_purchase_link";"""


MODELS_STATE = (
    "eJztXWtzozi6/itUvmxSJ9sLGGzcdeZUJd2Z2eymO6kkM7u1kykXCDmhYoMH43Rn98z57U"
    "c3QFyNHNsBrC/dsdEr8CMh6X3e23+O5oELZ8sPN2HgrkB09FH5z5FvzyH6I3/pVDmyF4v0"
    "Av4isp0ZabvgGjnLKLRJX1N7toToKxcuQegtIi/wceOHFbA08LByDctSHla6qhnoP3egqQ"
    "8rZwwN9Lc5VNFXQAUaa4b+t8HI+KDkhMHURO0dwwX4gzs2cDsVdQRGI6D8oIAQ2hF0J3b0"
    "AT+cGwD0dJ7/+M7PsfK931dwEgWPMHqCIXqaX39DX3u+C7/DZfxx8TyZenDmZobFc3EH5P"
    "tJ9Log31360Y+kIf6JzgQEs9XcTxsvXqOnwE9aez4ZqEfowxA/FPouCld4oPzVbMaGNB47"
    "+qRpE/qInIwLp/ZqhocbS9MHSL87mky+Xt9P7i7uJ5OjwlSIJbhRYV+BwMfTCD3qkvz6R/"
    "wIf9Y1Y2RYg6FhoSbkMZNvRn/QW6fAUEECz9f7oz/IdTuyaQuCcQpqOjxFcD+jK5E3h+UI"
    "ZyVzSLtM9EP8Rx73GOU64OMvUuTT92of0KMf6F77s1c25DU4319+ubi7P/tyg283Xy5/nx"
    "H8zu4v8BWdfPua+/Z4eIK/D9CSQZeSpBPlH5f3f1XwR+Vf118vCLzBMnoMyR3Tdvf/OsLP"
    "ZK+iYOIH3ya2y83O+NsYNdQyHfXVwt1w1LOSctTbMuoxRtyws6fn3nW0fRXH+9OTHVa84a"
    "x9bpQRWpuM6/suo3P7+2QG/cfoCX001ZpR/eXs9tNfz26PTTU3Ul/ZFZ1c+iMD7eIpQLiv"
    "wpkIvhmhjUBmELbm3cmgrKlqE5xxs0qk6cUs1pEXzeAE+CJQ8zLbmc6tgnrQCOlBDdCDKp"
    "yfA3GcqUz/ZvROYEYqBdxsL85KbmEvbhn43d166YkLazLTZ+7Yjb9wbPD8zQ7dSeYKt5OE"
    "HoCT5Sp8ga/L4ow4Z+I//v0WzmyCaHHsEwUWdXVHeurgCvdHPN3jb8uONBgt1MmbgSJK/A"
    "3trE9Y4RkX6EHVHMxe4tekyPZmk4X9WHJgjJG99uF9gP5Zj+9n0t0N662Ti1A5tHN9noN2"
    "bvvoZ7qsOyxc8jKWkk2Zd7WOcErXh6asEyVkbGCPCXszwuyMaoOU+uEYHcLz4E/OeIRbuL"
    "ozJg1M9MFRbSw7dtF1YLpqpjvMGplYxIYDTCRZpptjizTlY/YBvpZxUy1+2gcf/TkcmOhf"
    "zSTsl6u5pJFl4mcwLfSvPqYPSUkw2yR3svCDAPIIpmHjp4aqEpAxWirxjwC6ZpFHIVyaNs"
    "C/S4eGcoz+N9lTgtK+HXtEbqpj8g7/BiX/oKRrMDToIziYpoOqQ0Fi1/F/I8uiNz2RdJ2k"
    "67q0B3aUuJF03SGOuqTr3pWuo8enCZ735W9UOcI5sbrXqYOvUg3I+HWQjOf7MZ524NjCYG"
    "elesh67gpuEKwWtv84mXv+hKhbAgfZUtn159oOzPStnGyLIAtO6pyYXEOaTmrffoHhRlO6"
    "RFJO6OKEpjAJTueMkJzMTSeztJn01WaSJfcJLT8RYpKyQhstVK079WxhpSrYogowFzH+MQ"
    "ih9+j/Hb4SqC/RQ9l+6QZQ9JjsGMRVLD/6OrS/JexmbnYhBOh6Qhb5s7tPZ5+RmtTEyseY"
    "363Z964XcdOeAC+tfAJYCVn5NrdbXcdPXGe9SmdiMxvWJEgFGjlQFww4nJ2DmYMSs41rDs"
    "fKf2H7iju1FN60RGw9Q9U6yXSg/UB8nsfU81n5E25rqdSg9KfTTFP9h/gxwGiEjS5jy1L+"
    "dIVaDcYfxsSkMlINYu6xyj2wu/pDpE1I2oQ6smJ21DogbUKHOOpNbEJ0s9REKAZOpIccsN"
    "6IYNBr+AW9SC9QyHRxlPV+0jg7AZkeAoH/WrJ+QeDN7VmVgs/J5VcvKviBddDB2V1nhLv4"
    "dPnl7OpY0091AjRalzyqe8ZDYMjAhHdkJZlCI3TIzchItmo9W5V6Pr6ZrOqjd/RpjrDKzK"
    "/N+Sqy6L6Rf6HMwE1sQ+oJ4JkVwLGXcBJMJ+9EWLVs1X0XvuriO3iy/Ud4a5NpXqCqMtdP"
    "61gqyFpOwrhpE35qOMIOtK6lKmc3lwp1PMZECyFzHKA5mE8xsrQKdlweEhfhkU68cOEYy+"
    "gu5/TM/HwtmA3Fz98OE0OENZq6sZ+vMwC4A2cMmBMy+XtMvY51fFPiaExdi20A8EOpjkpp"
    "KeoMXEpg9feXSoZLMlwd2ZY6ynVIhusQR70JwyXqk7srZ9x3XVDFXHGB/zp5Dr8J8iic1I"
    "GyKEZjFmUZrMIyn7lqCiWV6CHpuh2HfIHw6H0pDFfB4zqdATdprjZMZqx5E9VBI4GMwDK4"
    "w20m0A/kj89p7GJ6fKYJvPCRmnRDwgJH+JTtDFx8FFZVZ6TEx2MbqlZ6WjcNLDnUDdpzpr"
    "FGjMcajRHEwY6WbsZHbRKkmJqxx/S0r5P4zYE2oDGRaSwjzRKGrc3MoI0ujcYW7kBlcYd5"
    "XUNCQ6Ah8afJD1e436JlU63l9Js4+tWYqkmAaqwSIQ0tM2WPyzSwk9g7AMetEv8B+oiuQR"
    "Un2mMCOfn1QOpSUpfq1CbXzVO11KUOcdQbRZBKxUAqBt1TDDKuGM4Shi8VK1eNO0ZWrH82"
    "bKMJ0kY10kabVDDeMliifuUMh9WqF3XCScPUmhls8k63+HBLcqbwCZEBwKdwB4B8pmSiju"
    "CT+9BVy3WXrd+g5Ej9a+wjT8ab/rzf5DlbnrNbuWd088Qlz9mHOOpNztlLewaFw6qzQtL1"
    "qySkeuYtI3S/yWMYrBZFaO+QDjKrxLcg3KOg9YE+Gibg4g91uN4hreaqCK63nGB3pSKs50"
    "Ewg7Zfsf2nUjk8HSS2qzmbfLNflfD8+voqswSdX97nDtQ/fzm/uD3WcgpjEW12NBU6amVk"
    "5AJRgio79IpGiPNCEtcmEeKJbrGdCPH+xeCeFgLF+UlW7nhbXB+2gnB/g8LzIGcWSFHn5t"
    "0GTWemeXVxKe5FWFtjasK9hoK1phoTD9ncu5pOs8mapZlxKzph91pTdeo9nohYT4FObMQj"
    "k1pwOW9Rg9qOU6/VBhl8S6ia1DI8dNXCdzQNL8vzCzb1Rv2VT9qxmNnRNAjnkvCRhE871/"
    "OOqv6S8DnEUW9C+CRLbmHMsUnqwl/NC6e1rArCybfZDHj06frnm7OvP31UWN7FB//r2S8X"
    "t6gvnLguv8U3MVzpzUKJayKJ8ybC6fckQkfAys1JvY+VW1fV3R6ft2bkRlCJemVzIm90zG"
    "4ZASfmmY1gmNvh82oxWZQlWFs3QbOy7zNN33GSmgJx7ssnb7HACvcUCpHwObH9sUE4gHxX"
    "2G6dZmPbFUZpk7W2VP4QfYtEZvTCfp1DP9oY8xJxuYLU4E1jtzeg6YuCPbI0bZGql8lcd4"
    "GrTDqyLVRrDSAyRW5zy8f6FLnFCbxdy0eP4W2Q0KViV3sn41LL9rWmOBd39QzY6DGUrz9f"
    "XYmke57ILDrvkhKGKz9aYonLFiettsLlaqI2ssCpJDZQG+AAvsHYSlPsEjtSZTlL5WNis1"
    "LutP+7I8UsHdyL7Q5BbLhiSXuZ4cpQFYRqhI78x3+7u/56cqrcDYldaYrNV5pjUsMVtjup"
    "OFcKM34ZUy0J2QO49qM7HMRFLFNkPgXzeeCXmvR69hOJjZAWER2NLOWHbDgouz3NxFx1W1"
    "aKlD67M7JAGi05GuDr9oBcB7ixqw5TI6A7NE16Y5Lx2SJGzvRh8G+xSRwruQ8Y2uOkawdo"
    "uGtVBUkxUJbxmRb2dAbEjAq5KqLOAIA4shVHw8oEONK22L0dpaNWJmlbPMRRbxS0SfeY4p"
    "DjPa/iJU9F8mPtgUj5XwX7QndwlGtGFYORGdDYQnj85eyfeePhp6vr8/xI4Q7O81xKZEer"
    "kvN5M6NuKr0/k+6RG9rT6EgM/6PPt2c/3n9UiOyDf3vxy+XFPz4qIXzx4LcH/+zm5vb6l4"
    "vPHxV0GA6DF+g++AjZrz9d3H1UaKKIZTssv/SJN1ohc6KyEFh7VsTiRkgHC10us4Lcw+8V"
    "p8ucWB+CgOtG9eKf9/UrYjKoV9dff4qb55fJsjdsAp4geC5ZGKu3pILgmzam7ozCTvalZL"
    "FyBIn+oqA0TRVNKPFpWRTdgpwEt8V2v84TBDX2qXQmboHk/3kJu7szruX1Cy9tBa1fsf5K"
    "fNfgW9xy3mA3gd8XQRi90WKScrwXpLvuKsL1xQco8lsD65Z01yewijamBhb+ax/eB+if3d"
    "v325BxePsFcLdkuaPmmaNa+x1rc9rQiod+bNK+gTHPsW1s4jFI1Fed2SuJ+bKBlhpouNyb"
    "xGrlmqQ9qWpATV40howaalzTGmfMSsTkVG7K+qCw9rFp7dhzf9BKcxF18jdIY5Q0RnVk6+"
    "moWUIaow5x1JsYo0L4iC6VW0SqKKdYYo9WEEEDSPOR3XF2yyWczagy2BTeVKJ38GpNqzLW"
    "FWXMI+wHES4XGnnRTChNa15Oot0cbRE7QSohLddvsBBICluSrS2gWE43JFvfJ0tPgRisZR"
    "dS8rAZuwDT9kKuwkqshzvONM05w1xLwdSI/2ZlSGIP28RNFKvYGlir3zMv1XzKHPIVdFle"
    "nr/d/ES8d0eUEMDd8SUUS2qwpDVAPpQn5OGrotCCLqiXuOaJlhZHIaVW0ENaNRUoJWb1mD"
    "34zDNs8mQvn4gzM6spM3bUpHoMsDSVPXsD/+aU9sFFO48fstVy0kv4cUgaJfwk5KmMxDMZ"
    "DDWnZMhOPiTe1mBIytbw+ZbSQjk1WZGYcz6fX+MFhkuZDluSRq09K3aUPpCk0SGOehPS6G"
    "CyI/G5kB78fK6k/InlfXxk4+2v+ZbGScjY8BKPJv5MJUIp5eXaPLU3JJWGRoPpOzQqpy++"
    "lAU7gnO8HAhxd7xM73i77ZPQU29WFpRczdklApKyewNlF59rRSm7gpyk7Eq8TjEDI+Zymk"
    "rIXa9BRhSmab+R/swG33cM4sY+U+nUWp+wI329Jbu8BtfCSthSdpl5Utayy6m3ZTN2OUzb"
    "N2CXM6kAyipjZxqAISlCDWyXT1zOpSHIJjO3NLNKiC+u7Rgk6TlJOuCMHSBC9uWI367/HO"
    "nRJsnJjuxxHaWpJDl5iKPehJxEO2UpHdaMmkyl28zeHN39fP7l8v6jslw5cy9KQvqTiP5i"
    "QD9OA4B6w1kAljBqB3UpGu8tA703D/QWj/CWod3bYIEkUbH1aG6k8wo6waUSkkuTzM97MT"
    "+rZZkruOR8sh6F6bvaKrbnbOGhIToq4XjYldM6ZsdeeJNn1qiJs2BCRJCckSwXpHJ2c4ld"
    "sFTbwH5ZzpjkztRIkT3spbZ89mYzFoF3QgPuaLCeaSj//DMS/jN6TiVNDwk0Zx0R8z4PQn"
    "J0kuJ6NGMoq9fnkHqCNlTHJHsm+co0iMOeyTqyqDcd/YDdAoEJiQfcFLCCfp/PCWnjxnGO"
    "yydbN7lYR+LZFndhmPEjsZ9Ln5mJxh+oyx11M8RMEj5h2yF4It54ODsoq/dHOwXG1FJS7m"
    "pkxa5/xwCtBH9Bqs0TmvaL5YfFqwyPlGRSp7bNjtIKkkw6xFFvQiaR/wvjXRNVxtq3mTxq"
    "UzwZOhNNFiGcet9FUM5K9RHrYROo8+8Fh/SwDGhRfzZeZjsgv++5YMeebJg6filZLc6DYA"
    "ZtvxzjVCiHsIOkdjWPY9T3S6+dX19fZZb988s8b/nzl/MLNLFzJb2KFNDMXkYTpClush3n"
    "ZWVm2PbsvyXHrr2Tfa3bGXYc7LpXUqpt4L6VlSpPibU3UoqgXkJJxaNRR0gtJvHQN0qOlW"
    "M6iA8OqdqC3WlwlGBSDYVG+Zk4XhKzNA9xYZcQfljAcO4tcfDB8sMt2hVp/im9NJPVzm8o"
    "eRXJq3Rkmeqohi15lUMc9Sa8Ct56RLkVXqZ36uj2o34kdbVDcBf2cvktQMc3UU6lINhDuH"
    "fCFIaBWH6vuH0P8d2+I56krvZGXS0hUUcm4mHbJZL7Izi0FisVBXajWhkvSfnPBd1sLbV6"
    "ZznD+gT00PUiidjmiNF85FvDLE2H3kPkipnW9l8louu4vVfBiC7ixjz03ghW6gvYsRNmI4"
    "xing2tYwvbf53YAAQr/60v5ifa2xntrKfTK9H7tvBGZgG7YT3/0rNiLmUTD7+k6G8X+pFn"
    "z97+rn5K+urptMOALSGCLNrGxMsgdke6PYRZFy93nj8NtvPqXqKeejrjYtCWT95igXrDpH"
    "CINNe3qgp3rL8z2l1P0UPrOAwn8AW+eVe9xj1dvMDe7qgUquWrDybh6q1KFUHrDvV1u+qr"
    "QhW/mJEdOHYwWaxC8GS/+bW8J73dsM56Cp2ErBFku/R0ySkJJT4vRTWi2vslp8CQxg2cYN"
    "whjuahjiesfBpXMS0ulOa4FrlC4qEcaJCoItsoOLC4Kk0mQ3J6A82I/8YhROjvKcQl1ga6"
    "Fn/jaLqR5NQGlpEEWB3lhq3dTyrdbqTbTUe0hI46YEi3m0Mc9SZuN/WJuys8FjqSrLtNzg"
    "qrcCYCMWveh7Q2ecebZp43da43BXBnwaPnl8YEVCPMy/RwEuuNcNZrcNaLOCeUNfRBEevq"
    "LE15uV7gve90TatluXW9Ol1TKrH/rN1H/z1d+SRzmuKsvFnk+csP+H7/c7T/4dhJFica8b"
    "HJcSkrKYPN2nM6Kh6KZcb2/cWdyTTYe0yDLe3QXWA1MwiuZTjzeDdmOyeZOdCU+6T0oANw"
    "cUOaZ8kd0rqMJim/OLKylQ7TXN2OjksZYhbylDR3aBJucJzyRyfsCsm2NFYzBCQJ5yP9uL"
    "oRp4nCybffkF+82z9GMqiSQe3IqtpRLk0yqIc46k0YVG8hQjvR1v3j9XaRPIeeTYQ2qKyQ"
    "zPbRimTJfUS0Ro/lXAjeqMQK+0G3Demm+mz2tW1b3uSuolqVouYWbXm3l5/u3zFxMudmXZ"
    "4/OeuHXZ9GGWTbbtdth0tsTJIPD4nCBkiW46JTC4AkrbFNchTrtkGl42JSiVuMcr2APr2W"
    "ZESuTW9znF0KTvC1KUlIbDKNNJeduETF7f+PxlmiaU5mLp0zTbOMm+N/0U1A4qY0skGcpR"
    "mMx26i4CN0El8m1wQWy3F9eaOkyJEszVSnx95SJLMzIQ/GNs01rY9J7miXgqXQR8TXR1Jz"
    "f+/TkNTcD0eHk5r7IY56E80dHY9ePCCUQ4QT6YUTg/R86rbn02LlzDwwebFnKzHfkIKgdB"
    "HZuouIt1yu0NZQltIFbyoVBzVeqG4/6d77UIM/3g5y6MHvCw+BKwhfVuqQ8UP7Ni4cMw2D"
    "EufeagBzYhJBpJttgB8VOmT07NkswNmUvIXQxpQTk9vS1relOZyXzOhq7924fR+OZPt22p"
    "VeotJLVHqJSi/RznuJ0pQx288W00HO5F38QsugW2c5SxFuaj9jmYGamtF4p0lcREHRyP/E"
    "TkTLZrrqkNS5dKbUnnIGAFwuFfSG0s/0ERVW/DO2CuG+WM2GH2HoowbY1ILNPNgpk9YA5R"
    "wwbXtMnTKTaPPEqoQva8S+446pA6dqMffKEgtZ53+PtCZJa1JHVtGO2hWkNekQR72JNQlB"
    "DoUsHYlADy1J26+vQCwVooHHGaFewLxvAmPJ8iJnEb+b27NZdVp6JrM/Z1F1t+eDgT4aJk"
    "cD/KHuVHD35ezqquh2yx2yRTmCrJx0wW1EEnAegW8kCUSzwrYNawG6IDvTROsacou1zCzb"
    "Pr6gKoi0BmlB3mDj8FGibO8q1jJ/o12Hj3bvx0jaQNIGHVlMO6pAStrgEEddho++X/goO5"
    "EI7U8ZGalnyeDR/WuuqQFum1pr72ytpzndNfPmyvjRfseP8iVTqpMixRVV1mdB8uKWQpGj"
    "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"
    "zI/n3q38cquDXv+cJhbJ+b2R//DznZJJI="
)
