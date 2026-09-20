#include "PartnerMatcher.h"

// Implement the required functions here
PartnerMatcher::PartnerMatcher(Semester semester, int year) {
    this->courseArray = nullptr;
    this->numCourses = 0;
    this->studentArray = nullptr;
    this->numStudents = 0;

    this->mappingHead = nullptr;

    this->semester = semester;
    this->year = year;
};

PartnerMatcher::~PartnerMatcher() {
    delete [] this->courseArray;
    delete[] this->studentArray;

    if (!mappingHead) return;

    PartnerScoreMappings * curr = this->mappingHead->next;

    while (curr!= mappingHead) {
        PartnerScoreMappings * next = curr->next;
        delete curr;
        curr = next;
    }

    delete mappingHead;
    mappingHead = nullptr;
};

PartnerMatcher& PartnerMatcher::addStudent(Student &student) {
    Student ** NewStudentArray = new Student*[this->numStudents+1] ;
    
        int p=0;
        int q=0;
        while (p<numStudents && studentArray[p]->getId() < student.getId()) {
            NewStudentArray[q] = studentArray[p];
            p++; q++;
        }

        NewStudentArray[q] = &student;
        q++;

        while (p<numStudents) {
            NewStudentArray[q] = studentArray[p];
            p++;q++;
        }
        this->numStudents ++;
        delete[] this->studentArray;
        this->studentArray = NewStudentArray;
        return *this;
}

PartnerMatcher& PartnerMatcher::addCourse(const Course &course) {
    const Course ** new_courses = new const Course*[numCourses+1];
    const Course * new_course = &course;

    int p=0;
    int q=0;

    while (p<numCourses && course.compareTo(*courseArray[p]) > 0) {
        new_courses[q] = courseArray[p];
        p++;q++;
    }

    new_courses[q] = new_course;
    q++;

    while (p<numCourses) {
        new_courses[q] = courseArray[p];
        p++;
        q++;
    }

    delete[] courseArray;
    courseArray = new_courses;
    return *this;
};

void PartnerMatcher::updateMappings() {
    if (numStudents ==0 || numStudents ==1) return;
    
    if (mappingHead != nullptr) {
        PartnerScoreMappings * curr = mappingHead->next;

        while (curr!= mappingHead) {
            PartnerScoreMappings * t = curr->next;
            delete curr;
            curr = t;
        }

        delete mappingHead;
        mappingHead = nullptr;
    }
        PartnerScoreMappings * prevnode = mappingHead;
        for (int i=0; i<numStudents; i++) {
            for (int j=i+1; j<numStudents; j++) {
                    PartnerScoreMappings * new_mapping = new PartnerScoreMappings;
                    new_mapping->student1 = (studentArray[i]->getId()<studentArray[j]->getId()) ? studentArray[i] : studentArray[j];
                    new_mapping->student2 = (studentArray[i]->getId()>studentArray[j]->getId()) ? studentArray[i] : studentArray[j];
                    new_mapping->score = new_mapping->student1->calculateScore(*(new_mapping->student2));

                    if (mappingHead == nullptr) {
                        mappingHead = new_mapping;
                        new_mapping->prev = nullptr;
                        new_mapping->next = nullptr;
                        prevnode = new_mapping;
                    }

                    else {
                        PartnerScoreMappings * curr = mappingHead;
                        while (curr!= prevnode) curr = curr->next;

                        curr->next = new_mapping;
                        new_mapping->student1 = (studentArray[i]->getId()<studentArray[j]->getId()) ? studentArray[i] : studentArray[j];
                        new_mapping->student2 = (studentArray[i]->getId()>studentArray[j]->getId()) ? studentArray[i] : studentArray[j];
                        new_mapping->score = new_mapping->student1->calculateScore(*(new_mapping->student2));
                        new_mapping->prev = curr;
                        new_mapping->next =nullptr;
                        prevnode = new_mapping;
                    }  
            }
        }

        mappingHead->prev = prevnode;
        prevnode->next = mappingHead;
    
        if (numStudents<3) return;
        
        PartnerScoreMappings * curr = mappingHead->next;
        while (curr != mappingHead) {
            PartnerScoreMappings * left = curr->prev;
            PartnerScoreMappings * right = curr;
            while ( right != mappingHead && (
                left->score > right->score || (
                left->score == right->score && left->student1->getId() > right->student1->getId()
            )||(
                left->score == right->score && left->student1 ->getId() == right->student1->getId() && left->student2->getId() > right->student2->getId()
            ))
            ) {
                Student* s1 = right->student1;
                Student* s2 = right->student2;

                double scr = right->score;

                right->student1 = left->student1;
                right->student2 = left->student2;
                right->score = left->score;

                left->student1 = s1;
                left->student2 = s2;
                left->score = scr;

                left = left->prev;
                right = right->prev;
            }

            curr = curr->next;
        }
        
};
//until above debugged
//to debug the following
void PartnerMatcher::matchStudents(MatchMode matchMode) const {
    if (numStudents ==0 || numStudents ==1) return;
    else if (numStudents ==2) {
        studentArray[0]->setPartner(studentArray[1]);
        studentArray[1]->setPartner(studentArray[0]);
        return;
    }
    for (int i=0; i<numStudents; i++) studentArray[i]->setPartner(nullptr);

    if (matchMode == MOST_SIMILAR) {
        PartnerScoreMappings * curr = mappingHead->prev;
        do{
            if (curr->student1->getPartner() == nullptr && curr->student2->getPartner() == nullptr) {
                curr->student1->setPartner(curr->student2);
                curr->student2->setPartner(curr->student1);
            }
            
            curr= curr->prev;
        }while (curr != mappingHead->prev) ;

        return;
    }

    else if (matchMode == LEAST_SIMILAR){
        PartnerScoreMappings * curr = mappingHead;
        do {
            if (curr->student1->getPartner() == nullptr && curr->student2->getPartner() == nullptr) {
                curr->student1->setPartner(curr->student2);
                curr->student2->setPartner(curr->student1);
            }
            curr = curr->next;
        } while (curr != mappingHead);
        return;
    }
};

PartnerMatcher& PartnerMatcher::moveToNextSemester() const {
    Semester new_sem = Fall;
    int yearr = -1;
    switch(this->semester) {
        case Fall: 
            new_sem = Winter;
            yearr = year+1;
            break;
        case Winter: 
            new_sem = Spring;
            yearr = year;
            break;
        case Spring: 
            new_sem = Summer;
            yearr = year;
            break;
        case Summer: 
            new_sem = Fall;
            yearr = year;
            break;
    }

    PartnerMatcher* new_system = new PartnerMatcher(new_sem, yearr);
    for (int i=0; i<numCourses; i++)
        new_system->addCourse(*(this->courseArray[i]));
    for (int j=0; j<numStudents; j++)
        new_system->addStudent(*(this->studentArray[j]));

    return *new_system;
}


// The following functions are implemented for you.
// DO NOT MODIFY THE LINES BELOW.
Semester PartnerMatcher::getSemester() const {
    return semester;
}

int PartnerMatcher::getYear() const {
    return year;
}

void PartnerMatcher::printStudents() const {
    for (int i = 0; i < numStudents; ++i)
        studentArray[i]->printInfo();
}

void PartnerMatcher::printAllMappings() const {
    if (!mappingHead) {
        cout << "No mappings." << endl;
        return;
    }
    const PartnerScoreMappings *ptr = mappingHead;
    do {
        cout << "Score between students with IDs " << ptr->student1->getId() <<
            " and " << ptr->student2->getId() << " is: " << ptr->score << endl;
        ptr = ptr->next;
    } while (ptr != mappingHead);
}
