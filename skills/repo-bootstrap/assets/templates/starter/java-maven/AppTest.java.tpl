package {{JAVA_PACKAGE}};

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertEquals;

class AppTest {
    @Test
    void returnsProjectName() {
        assertEquals("{{PROJECT_NAME}}", App.greeting());
    }
}
