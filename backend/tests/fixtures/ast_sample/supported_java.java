package com.platform.billing;

import java.math.BigDecimal;
import java.util.List;

public interface PaymentGateway {
    boolean chargeAccount(String accountId, BigDecimal amount);
}

public class StripeGateway implements PaymentGateway {
    public static final int DEFAULT_TIMEOUT_MS = 5000;
    private final String apiKey;

    public StripeGateway(String apiKey) {
        this.apiKey = apiKey;
    }

    @Override
    public boolean chargeAccount(String accountId, BigDecimal amount) {
        if (!validateAmount(amount)) {
            return false;
        }
        return true;
    }

    public boolean validateAmount(BigDecimal amount) {
        return amount != null && amount.compareTo(BigDecimal.ZERO) > 0;
    }
}
